"""Creator-scoped persistence for governed V3 knowledge and shadow evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Iterable

from sqlalchemy import Integer, and_, desc, func, insert, or_, select, update

from src.conversation.brain2_schema import CONVERSATION_OUTCOMES, FAN_MEMORIES_V2
from src.conversation.intelligence_v3.knowledge import (
    ExtractedDocument,
    lexical_score,
    tokenize,
)
from src.conversation.intelligence_v3.schema import (
    CONVERSATION_DOCUMENT_PAGES,
    CONVERSATION_INTELLIGENCE_RUNS,
    CONVERSATION_KNOWLEDGE_CONFLICTS,
    CONVERSATION_KNOWLEDGE_RULES,
    CONVERSATION_QUALITY_FEEDBACK,
    FAN_CALLBACKS,
    FAN_STATE_TRANSITIONS,
)
from src.human_delivery.schema import CONVERSATION_DOCUMENTS, CONVERSATION_EXAMPLES
from src.persistence.schema import utcnow


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fingerprint(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class KnowledgeRepository:
    """Persist upload extracts, explicit rules, conflicts, and approved examples."""

    def __init__(self, engine, *, creator_id: str):
        self.engine = engine
        self.creator_id = creator_id

    def ingest(self, extracted: ExtractedDocument, *, actor: str = "operator") -> dict:
        now = utcnow()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(CONVERSATION_DOCUMENTS).where(
                    and_(
                        CONVERSATION_DOCUMENTS.c.creator_id == self.creator_id,
                        CONVERSATION_DOCUMENTS.c.source_fingerprint
                        == extracted.fingerprint,
                    )
                )
            ).mappings().first()
            if existing is not None:
                return {**dict(existing), "cached": True}
            revision = int(
                connection.execute(
                    select(func.coalesce(func.max(CONVERSATION_DOCUMENTS.c.revision), 0)).where(
                        and_(
                            CONVERSATION_DOCUMENTS.c.creator_id == self.creator_id,
                            CONVERSATION_DOCUMENTS.c.document_type == "sales_playbook",
                        )
                    )
                ).scalar_one()
            ) + 1
            result = connection.execute(
                insert(CONVERSATION_DOCUMENTS).values(
                    creator_id=self.creator_id,
                    document_type="sales_playbook",
                    revision=revision,
                    status="draft",
                    content=extracted.content,
                    document_name=extracted.name,
                    mime_type=extracted.mime_type,
                    source_fingerprint=extracted.fingerprint,
                    extraction_status=extracted.status,
                    extraction_report=extracted.report,
                    page_count=len(extracted.pages),
                    character_count=len(extracted.content),
                    conflict_findings=[],
                    source="pdf_upload",
                    created_by=str(actor)[:64],
                    created_at=now,
                    updated_at=now,
                )
            )
            document_id = int(result.inserted_primary_key[0])
            for page in extracted.pages:
                connection.execute(
                    insert(CONVERSATION_DOCUMENT_PAGES).values(
                        document_id=document_id,
                        creator_id=self.creator_id,
                        page_number=page.page_number,
                        content=page.content,
                        content_fingerprint=page.fingerprint,
                        extraction_quality=page.quality,
                        unreadable=page.unreadable,
                        created_at=now,
                    )
                )
            row = connection.execute(
                select(CONVERSATION_DOCUMENTS).where(
                    CONVERSATION_DOCUMENTS.c.id == document_id
                )
            ).mappings().one()
        return {**dict(row), "cached": False}

    def create_rule(self, payload: dict, *, actor: str = "operator") -> dict:
        required = ("rule_key", "knowledge_profile", "knowledge_type", "scenario")
        values = {key: str(payload.get(key) or "").strip() for key in required}
        if any(not value for value in values.values()):
            raise ValueError("rule key, profile, type, and scenario are required")
        if values["knowledge_profile"] not in {
            "conversation",
            "relationship",
            "sales",
        }:
            raise ValueError("invalid knowledge profile")
        status = str(payload.get("status") or "draft").strip().lower()
        if status not in {"draft", "approved", "active", "archived"}:
            raise ValueError("invalid rule status")
        source_document_id = int(payload.get("source_document_id") or 0)
        source_page = int(payload.get("source_page") or 0)
        if source_document_id <= 0 or source_page <= 0:
            raise ValueError("a source document and page are required")
        search_text = str(payload.get("search_text") or "").strip()
        if not search_text:
            raise ValueError("source-backed rule text is required")
        now = utcnow()
        with self.engine.begin() as connection:
            source_exists = connection.execute(
                select(CONVERSATION_DOCUMENT_PAGES.c.id).where(
                    and_(
                        CONVERSATION_DOCUMENT_PAGES.c.creator_id == self.creator_id,
                        CONVERSATION_DOCUMENT_PAGES.c.document_id == source_document_id,
                        CONVERSATION_DOCUMENT_PAGES.c.page_number == source_page,
                    )
                )
            ).scalar_one_or_none()
            if source_exists is None:
                raise ValueError("the cited source page does not exist")
            version = int(
                connection.execute(
                    select(func.coalesce(func.max(CONVERSATION_KNOWLEDGE_RULES.c.version), 0)).where(
                        and_(
                            CONVERSATION_KNOWLEDGE_RULES.c.creator_id == self.creator_id,
                            CONVERSATION_KNOWLEDGE_RULES.c.rule_key == values["rule_key"],
                        )
                    )
                ).scalar_one()
            ) + 1
            result = connection.execute(
                insert(CONVERSATION_KNOWLEDGE_RULES).values(
                    creator_id=self.creator_id,
                    **values,
                    conditions=list(payload.get("conditions") or [])[:20],
                    relationship_stages=list(payload.get("relationship_stages") or [])[:12],
                    recommended_acts=list(payload.get("recommended_acts") or [])[:12],
                    forbidden_acts=list(payload.get("forbidden_acts") or [])[:12],
                    priority=max(0, min(int(payload.get("priority") or 50), 100)),
                    source_document_id=source_document_id,
                    source_page=source_page,
                    source_excerpt_fingerprint=_fingerprint(search_text),
                    search_text=search_text[:8_000],
                    version=version,
                    status=status,
                    reviewer=str(actor)[:64] if status in {"approved", "active"} else None,
                    reviewed_at=now if status in {"approved", "active"} else None,
                    created_at=now,
                    updated_at=now,
                )
            )
            row = connection.execute(
                select(CONVERSATION_KNOWLEDGE_RULES).where(
                    CONVERSATION_KNOWLEDGE_RULES.c.id
                    == int(result.inserted_primary_key[0])
                )
            ).mappings().one()
            conflict_count = self._detect_rule_conflicts(
                connection,
                dict(row),
                now=now,
            )
            if status == "active" and conflict_count:
                connection.execute(
                    update(CONVERSATION_KNOWLEDGE_RULES)
                    .where(CONVERSATION_KNOWLEDGE_RULES.c.id == int(row["id"]))
                    .values(status="approved", updated_at=now)
                )
                row = connection.execute(
                    select(CONVERSATION_KNOWLEDGE_RULES).where(
                        CONVERSATION_KNOWLEDGE_RULES.c.id == int(row["id"])
                    )
                ).mappings().one()
        return dict(row)

    def _detect_rule_conflicts(
        self,
        connection,
        rule: dict,
        *,
        now: datetime,
    ) -> int:
        """Create review gates for explicit act contradictions in the same scenario."""
        peers = connection.execute(
            select(CONVERSATION_KNOWLEDGE_RULES).where(
                and_(
                    CONVERSATION_KNOWLEDGE_RULES.c.creator_id == self.creator_id,
                    CONVERSATION_KNOWLEDGE_RULES.c.id != int(rule["id"]),
                    CONVERSATION_KNOWLEDGE_RULES.c.scenario == rule["scenario"],
                    CONVERSATION_KNOWLEDGE_RULES.c.status != "archived",
                )
            )
        ).mappings().all()
        recommended = {str(value).strip().lower() for value in rule.get("recommended_acts") or []}
        forbidden = {str(value).strip().lower() for value in rule.get("forbidden_acts") or []}
        stages = {str(value).strip().lower() for value in rule.get("relationship_stages") or []}
        conflicts = 0
        for peer in peers:
            peer_stages = {
                str(value).strip().lower()
                for value in peer.get("relationship_stages") or []
            }
            if stages and peer_stages and stages.isdisjoint(peer_stages):
                continue
            peer_recommended = {
                str(value).strip().lower()
                for value in peer.get("recommended_acts") or []
            }
            peer_forbidden = {
                str(value).strip().lower()
                for value in peer.get("forbidden_acts") or []
            }
            if not ((recommended & peer_forbidden) or (peer_recommended & forbidden)):
                continue
            conflicts += 1
            left_id, right_id = sorted((int(rule["id"]), int(peer["id"])))
            exists = connection.execute(
                select(CONVERSATION_KNOWLEDGE_CONFLICTS.c.id).where(
                    and_(
                        CONVERSATION_KNOWLEDGE_CONFLICTS.c.left_rule_id == left_id,
                        CONVERSATION_KNOWLEDGE_CONFLICTS.c.right_rule_id == right_id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                connection.execute(
                    insert(CONVERSATION_KNOWLEDGE_CONFLICTS).values(
                        creator_id=self.creator_id,
                        left_rule_id=left_id,
                        right_rule_id=right_id,
                        reason_code="recommended_forbidden_act_conflict",
                        status="open",
                        created_at=now,
                    )
                )
        return conflicts

    def set_rule_status(self, rule_id: int, *, status: str, actor: str) -> dict:
        if status not in {"draft", "approved", "active", "archived"}:
            raise ValueError("invalid rule status")
        now = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(CONVERSATION_KNOWLEDGE_RULES).where(
                    and_(
                        CONVERSATION_KNOWLEDGE_RULES.c.id == int(rule_id),
                        CONVERSATION_KNOWLEDGE_RULES.c.creator_id == self.creator_id,
                    )
                )
            ).mappings().first()
            if row is None:
                raise ValueError("rule was not found")
            if status == "active":
                open_conflict = connection.execute(
                    select(CONVERSATION_KNOWLEDGE_CONFLICTS.c.id).where(
                        and_(
                            CONVERSATION_KNOWLEDGE_CONFLICTS.c.creator_id == self.creator_id,
                            CONVERSATION_KNOWLEDGE_CONFLICTS.c.status == "open",
                            or_(
                                CONVERSATION_KNOWLEDGE_CONFLICTS.c.left_rule_id == int(rule_id),
                                CONVERSATION_KNOWLEDGE_CONFLICTS.c.right_rule_id == int(rule_id),
                            ),
                        )
                    )
                ).scalar_one_or_none()
                if open_conflict is not None:
                    raise ValueError("resolve rule conflicts before activation")
                connection.execute(
                    update(CONVERSATION_KNOWLEDGE_RULES)
                    .where(
                        and_(
                            CONVERSATION_KNOWLEDGE_RULES.c.creator_id == self.creator_id,
                            CONVERSATION_KNOWLEDGE_RULES.c.rule_key == row["rule_key"],
                            CONVERSATION_KNOWLEDGE_RULES.c.status == "active",
                        )
                    )
                    .values(status="archived", updated_at=now)
                )
            connection.execute(
                update(CONVERSATION_KNOWLEDGE_RULES)
                .where(CONVERSATION_KNOWLEDGE_RULES.c.id == int(rule_id))
                .values(
                    status=status,
                    reviewer=str(actor)[:64],
                    reviewed_at=now,
                    updated_at=now,
                )
            )
            updated = connection.execute(
                select(CONVERSATION_KNOWLEDGE_RULES).where(
                    CONVERSATION_KNOWLEDGE_RULES.c.id == int(rule_id)
                )
            ).mappings().one()
        return dict(updated)

    def resolve_conflict(
        self,
        conflict_id: int,
        *,
        resolution: str,
        actor: str,
    ) -> dict:
        note = str(resolution or "").strip()
        if not note:
            raise ValueError("a conflict resolution note is required")
        now = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(CONVERSATION_KNOWLEDGE_CONFLICTS).where(
                    and_(
                        CONVERSATION_KNOWLEDGE_CONFLICTS.c.id == int(conflict_id),
                        CONVERSATION_KNOWLEDGE_CONFLICTS.c.creator_id
                        == self.creator_id,
                    )
                )
            ).mappings().first()
            if row is None:
                raise ValueError("knowledge conflict was not found")
            connection.execute(
                update(CONVERSATION_KNOWLEDGE_CONFLICTS)
                .where(CONVERSATION_KNOWLEDGE_CONFLICTS.c.id == int(conflict_id))
                .values(
                    status="resolved",
                    resolution=note[:2_000],
                    reviewer=str(actor)[:64],
                    resolved_at=now,
                )
            )
            updated = connection.execute(
                select(CONVERSATION_KNOWLEDGE_CONFLICTS).where(
                    CONVERSATION_KNOWLEDGE_CONFLICTS.c.id == int(conflict_id)
                )
            ).mappings().one()
        return self._sanitize_conflict(updated)

    def document_pages(self, document_id: int) -> list[dict]:
        with self.engine.connect() as connection:
            document = connection.execute(
                select(CONVERSATION_DOCUMENTS.c.id).where(
                    and_(
                        CONVERSATION_DOCUMENTS.c.id == int(document_id),
                        CONVERSATION_DOCUMENTS.c.creator_id == self.creator_id,
                    )
                )
            ).scalar_one_or_none()
            if document is None:
                raise ValueError("knowledge document was not found")
            rows = connection.execute(
                select(CONVERSATION_DOCUMENT_PAGES)
                .where(
                    and_(
                        CONVERSATION_DOCUMENT_PAGES.c.document_id
                        == int(document_id),
                        CONVERSATION_DOCUMENT_PAGES.c.creator_id
                        == self.creator_id,
                    )
                )
                .order_by(CONVERSATION_DOCUMENT_PAGES.c.page_number)
            ).mappings().all()
        return [
            {
                "page_number": row["page_number"],
                "content": row["content"],
                "extraction_quality": row["extraction_quality"],
                "unreadable": bool(row["unreadable"]),
            }
            for row in rows
        ]

    def retrieve(
        self,
        *,
        query: str,
        relationship_stage: str,
        profiles: Iterable[str] = ("conversation", "relationship"),
        rule_limit: int = 6,
        example_limit: int = 4,
    ) -> dict:
        profile_set = {str(value) for value in profiles}
        if "sales" in profile_set:
            profile_set.remove("sales")
        terms = tokenize(query, relationship_stage)
        with self.engine.connect() as connection:
            rule_rows = connection.execute(
                select(CONVERSATION_KNOWLEDGE_RULES).where(
                    and_(
                        CONVERSATION_KNOWLEDGE_RULES.c.creator_id == self.creator_id,
                        CONVERSATION_KNOWLEDGE_RULES.c.status == "active",
                        CONVERSATION_KNOWLEDGE_RULES.c.knowledge_profile.in_(profile_set),
                    )
                )
            ).mappings().all()
            example_rows = connection.execute(
                select(CONVERSATION_EXAMPLES).where(
                    and_(
                        CONVERSATION_EXAMPLES.c.creator_id == self.creator_id,
                        CONVERSATION_EXAMPLES.c.status == "active",
                        CONVERSATION_EXAMPLES.c.safety_class == "conversation_only",
                    )
                )
            ).mappings().all()
        rules = sorted(
            (dict(row) for row in rule_rows),
            key=lambda row: (
                relationship_stage in list(row.get("relationship_stages") or []),
                lexical_score(terms, row.get("search_text")),
                int(row.get("priority") or 0),
            ),
            reverse=True,
        )[: max(1, min(int(rule_limit), 6))]
        examples = sorted(
            (dict(row) for row in example_rows),
            key=lambda row: (
                str(row.get("stage") or "") == relationship_stage,
                lexical_score(
                    terms,
                    row.get("scenario"),
                ),
                int(row.get("revision") or 0),
            ),
            reverse=True,
        )[: max(1, min(int(example_limit), 4))]
        return {
            "rules": rules,
            "examples": examples,
            "fingerprint": _fingerprint(
                {
                    "rules": [(row["id"], row["version"]) for row in rules],
                    "examples": [(row["id"], row["revision"]) for row in examples],
                }
            ),
        }

    def overview(self) -> dict:
        with self.engine.connect() as connection:
            documents = connection.execute(
                select(CONVERSATION_DOCUMENTS).where(
                    CONVERSATION_DOCUMENTS.c.creator_id == self.creator_id
                ).order_by(desc(CONVERSATION_DOCUMENTS.c.created_at))
            ).mappings().all()
            rules = connection.execute(
                select(CONVERSATION_KNOWLEDGE_RULES).where(
                    CONVERSATION_KNOWLEDGE_RULES.c.creator_id == self.creator_id
                ).order_by(desc(CONVERSATION_KNOWLEDGE_RULES.c.updated_at))
            ).mappings().all()
            conflicts = connection.execute(
                select(CONVERSATION_KNOWLEDGE_CONFLICTS).where(
                    and_(
                        CONVERSATION_KNOWLEDGE_CONFLICTS.c.creator_id == self.creator_id,
                        CONVERSATION_KNOWLEDGE_CONFLICTS.c.status == "open",
                    )
                )
            ).mappings().all()
        return {
            "documents": [self._sanitize_document(row) for row in documents],
            "rules": [self._sanitize_rule(row) for row in rules],
            "open_conflicts": len(conflicts),
            "conflicts": [self._sanitize_conflict(row) for row in conflicts],
        }

    @staticmethod
    def _sanitize_document(row) -> dict:
        item = dict(row)
        item.pop("content", None)
        item.pop("source_fingerprint", None)
        return item

    @staticmethod
    def _sanitize_rule(row) -> dict:
        item = dict(row)
        item.pop("search_text", None)
        item.pop("source_excerpt_fingerprint", None)
        return item

    @staticmethod
    def _sanitize_conflict(row) -> dict:
        item = dict(row)
        item.pop("resolution", None)
        return item


class IntelligenceRepository:
    """Store evidence changes and privacy-safe V3 shadow telemetry."""

    def __init__(self, engine, *, creator_id: str):
        self.engine = engine
        self.creator_id = creator_id

    def record_transition(self, *, fan_id: str, transition: dict) -> bool:
        values = {
            "creator_id": self.creator_id,
            "fan_id": fan_id,
            "shadow": True,
            **transition,
            "created_at": utcnow(),
        }
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(FAN_STATE_TRANSITIONS.c.id).where(
                    and_(
                        FAN_STATE_TRANSITIONS.c.creator_id == self.creator_id,
                        FAN_STATE_TRANSITIONS.c.fan_id == fan_id,
                        FAN_STATE_TRANSITIONS.c.field_name == values["field_name"],
                        FAN_STATE_TRANSITIONS.c.source_message_id
                        == values["source_message_id"],
                        FAN_STATE_TRANSITIONS.c.state_version == values["state_version"],
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                return False
            connection.execute(insert(FAN_STATE_TRANSITIONS).values(**values))
        return True

    def upsert_callback(self, *, fan_id: str, callback: dict) -> int:
        subject = str(callback["subject"]).strip()[:2_000]
        subject_key = str(callback.get("subject_key") or _fingerprint(subject)[:32])[:128]
        now = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(FAN_CALLBACKS).where(
                    and_(
                        FAN_CALLBACKS.c.creator_id == self.creator_id,
                        FAN_CALLBACKS.c.fan_id == fan_id,
                        FAN_CALLBACKS.c.subject_key == subject_key,
                    )
                )
            ).mappings().first()
            values = {
                "subject": subject,
                "source_message_id": str(callback["source_message_id"])[:128],
                "first_mentioned_at": _aware(callback["first_mentioned_at"]),
                "resolved": bool(callback.get("resolved", False)),
                "emotional_sensitivity": str(callback.get("emotional_sensitivity") or "standard")[:32],
                "earliest_safe_reuse_at": callback.get("earliest_safe_reuse_at"),
                "current_relevance": min(max(float(callback.get("current_relevance", 0.5)), 0.0), 1.0),
                "updated_at": now,
            }
            if row is None:
                result = connection.execute(
                    insert(FAN_CALLBACKS).values(
                        creator_id=self.creator_id,
                        fan_id=fan_id,
                        subject_key=subject_key,
                        times_referenced=0,
                        created_at=now,
                        **values,
                    )
                )
                return int(result.inserted_primary_key[0])
            connection.execute(
                update(FAN_CALLBACKS)
                .where(FAN_CALLBACKS.c.id == row["id"])
                .values(**values)
            )
            return int(row["id"])

    def relevant_callbacks(self, *, fan_id: str, limit: int = 2) -> list[dict]:
        now = utcnow()
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(FAN_CALLBACKS).where(
                    and_(
                        FAN_CALLBACKS.c.creator_id == self.creator_id,
                        FAN_CALLBACKS.c.fan_id == fan_id,
                        FAN_CALLBACKS.c.resolved.is_(False),
                        or_(
                            FAN_CALLBACKS.c.earliest_safe_reuse_at.is_(None),
                            FAN_CALLBACKS.c.earliest_safe_reuse_at <= now,
                        ),
                    )
                ).order_by(
                    desc(FAN_CALLBACKS.c.current_relevance),
                    desc(FAN_CALLBACKS.c.updated_at),
                ).limit(max(1, min(int(limit), 2)))
            ).mappings().all()
        return [dict(row) for row in rows]

    def record_run(self, payload: dict) -> int:
        allowed = {
            "fan_id",
            "inbound_message_id",
            "current_decision_id",
            "status",
            "shadow",
            "versions",
            "prompt_fingerprint",
            "compilation_report",
            "understanding",
            "relationship",
            "strategy",
            "delivery",
            "candidate_fingerprints",
            "selected_candidate_fingerprint",
            "rejection_codes",
            "model",
            "model_calls",
            "latency_ms",
            "estimated_cost",
            "completed_at",
        }
        values = {key: value for key, value in payload.items() if key in allowed}
        values.update(creator_id=self.creator_id, created_at=utcnow())
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(CONVERSATION_INTELLIGENCE_RUNS.c.id).where(
                    and_(
                        CONVERSATION_INTELLIGENCE_RUNS.c.inbound_message_id
                        == values["inbound_message_id"],
                        CONVERSATION_INTELLIGENCE_RUNS.c.shadow
                        == bool(values.get("shadow", True)),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return int(existing)
            result = connection.execute(
                insert(CONVERSATION_INTELLIGENCE_RUNS).values(**values)
            )
        return int(result.inserted_primary_key[0])

    def record_feedback(self, payload: dict, *, reviewer: str) -> int:
        allowed_types = {
            "great",
            "acceptable",
            "too_generic",
            "wrong_tone",
            "wrong_memory",
            "repetitive",
            "overly_sexual",
            "too_long",
            "too_cold",
            "unsafe",
            "manual_rewrite",
        }
        feedback_type = str(payload.get("feedback_type") or "").strip()
        if feedback_type not in allowed_types:
            raise ValueError("invalid quality feedback type")
        with self.engine.begin() as connection:
            run_id = int(payload.get("intelligence_run_id") or 0)
            run = connection.execute(
                select(CONVERSATION_INTELLIGENCE_RUNS).where(
                    and_(
                        CONVERSATION_INTELLIGENCE_RUNS.c.id == run_id,
                        CONVERSATION_INTELLIGENCE_RUNS.c.creator_id
                        == self.creator_id,
                    )
                )
            ).mappings().first()
            if run is None:
                raise ValueError("intelligence run was not found")
            if run["current_decision_id"] is None:
                raise ValueError("this shadow run has no attributable decision")
            outcome_id = connection.execute(
                select(CONVERSATION_OUTCOMES.c.id)
                .where(
                    and_(
                        CONVERSATION_OUTCOMES.c.creator_id == self.creator_id,
                        CONVERSATION_OUTCOMES.c.conversation_decision_id
                        == int(run["current_decision_id"]),
                    )
                )
                .order_by(desc(CONVERSATION_OUTCOMES.c.created_at))
                .limit(1)
            ).scalar_one_or_none()
            versions = dict(run.get("versions") or {})
            values = {
                "creator_id": self.creator_id,
                "decision_id": int(run["current_decision_id"]),
                "intelligence_run_id": int(run["id"]),
                # Derive attribution from durable creator-scoped evidence;
                # never trust an outcome identifier supplied by the browser.
                "outcome_id": outcome_id,
                "feedback_type": feedback_type,
                "prompt_version": str(
                    versions.get("pipeline") or "conversation-intelligence-v3.1"
                )[:64],
                "playbook_version": str(versions.get("playbook") or "")[:64] or None,
                "model": str(run["model"])[:128],
                "fan_state_fingerprint": _fingerprint(
                    {
                        "relationship": run.get("relationship") or {},
                        "understanding": run.get("understanding") or {},
                    }
                ),
                "candidate_fingerprint": (
                    str(run["selected_candidate_fingerprint"])[:64]
                    if run.get("selected_candidate_fingerprint")
                    else None
                ),
                "edit_distance": payload.get("edit_distance"),
                "reviewer": str(reviewer)[:64],
                "created_at": utcnow(),
            }
            result = connection.execute(
                insert(CONVERSATION_QUALITY_FEEDBACK).values(**values)
            )
        return int(result.inserted_primary_key[0])

    def quality_overview(self, *, recent_limit: int = 30) -> dict:
        """Return aggregate and fingerprint-only operator telemetry."""
        with self.engine.connect() as connection:
            runs = connection.execute(
                select(CONVERSATION_INTELLIGENCE_RUNS)
                .where(
                    CONVERSATION_INTELLIGENCE_RUNS.c.creator_id
                    == self.creator_id
                )
                .order_by(
                    desc(CONVERSATION_INTELLIGENCE_RUNS.c.created_at),
                    desc(CONVERSATION_INTELLIGENCE_RUNS.c.id),
                )
                .limit(max(1, min(int(recent_limit), 100)))
            ).mappings().all()
            status_rows = connection.execute(
                select(
                    CONVERSATION_INTELLIGENCE_RUNS.c.status,
                    func.count(CONVERSATION_INTELLIGENCE_RUNS.c.id),
                )
                .where(
                    CONVERSATION_INTELLIGENCE_RUNS.c.creator_id
                    == self.creator_id
                )
                .group_by(CONVERSATION_INTELLIGENCE_RUNS.c.status)
            ).all()
            total_cost, total_calls = connection.execute(
                select(
                    func.coalesce(
                        func.sum(CONVERSATION_INTELLIGENCE_RUNS.c.estimated_cost),
                        0.0,
                    ),
                    func.coalesce(
                        func.sum(CONVERSATION_INTELLIGENCE_RUNS.c.model_calls),
                        0,
                    ),
                ).where(
                    CONVERSATION_INTELLIGENCE_RUNS.c.creator_id
                    == self.creator_id
                )
            ).one()
            feedback_rows = connection.execute(
                select(
                    CONVERSATION_QUALITY_FEEDBACK.c.feedback_type,
                    func.count(CONVERSATION_QUALITY_FEEDBACK.c.id),
                )
                .where(
                    CONVERSATION_QUALITY_FEEDBACK.c.creator_id
                    == self.creator_id
                )
                .group_by(CONVERSATION_QUALITY_FEEDBACK.c.feedback_type)
            ).all()
            outcome_row = connection.execute(
                select(
                    func.count(CONVERSATION_OUTCOMES.c.id),
                    func.coalesce(func.sum(CONVERSATION_OUTCOMES.c.reply_length), 0),
                    func.coalesce(
                        func.sum(CONVERSATION_OUTCOMES.c.composite_quality),
                        0.0,
                    ),
                    func.coalesce(
                        func.sum(
                            func.cast(CONVERSATION_OUTCOMES.c.fan_replied, Integer)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            func.cast(CONVERSATION_OUTCOMES.c.negative_signal, Integer)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            func.cast(CONVERSATION_OUTCOMES.c.bot_suspicion, Integer)
                        ),
                        0,
                    ),
                ).where(CONVERSATION_OUTCOMES.c.creator_id == self.creator_id)
            ).one()
        outcome_count = int(outcome_row[0] or 0)
        return {
            "statuses": {str(key): int(value) for key, value in status_rows},
            "feedback": {str(key): int(value) for key, value in feedback_rows},
            "estimated_cost": float(total_cost or 0.0),
            "model_calls": int(total_calls or 0),
            "outcomes": {
                "observed": outcome_count,
                "reply_rate": round(
                    int(outcome_row[3] or 0) / max(1, outcome_count),
                    4,
                ),
                "average_reply_length": round(
                    int(outcome_row[1] or 0) / max(1, outcome_count),
                    2,
                ),
                "average_composite_quality": round(
                    float(outcome_row[2] or 0.0) / max(1, outcome_count),
                    4,
                ),
                "negative_signals": int(outcome_row[4] or 0),
                "bot_suspicion_signals": int(outcome_row[5] or 0),
            },
            "recent_runs": [self._sanitize_run(row) for row in runs],
        }

    def fan_insight(self, *, fan_id: str) -> dict:
        normalized = str(fan_id or "").strip()
        if not normalized or len(normalized) > 128:
            raise ValueError("a valid fan ID is required")
        with self.engine.connect() as connection:
            latest = connection.execute(
                select(CONVERSATION_INTELLIGENCE_RUNS)
                .where(
                    and_(
                        CONVERSATION_INTELLIGENCE_RUNS.c.creator_id
                        == self.creator_id,
                        CONVERSATION_INTELLIGENCE_RUNS.c.fan_id == normalized,
                    )
                )
                .order_by(desc(CONVERSATION_INTELLIGENCE_RUNS.c.created_at))
                .limit(1)
            ).mappings().first()
            transitions = connection.execute(
                select(FAN_STATE_TRANSITIONS)
                .where(
                    and_(
                        FAN_STATE_TRANSITIONS.c.creator_id == self.creator_id,
                        FAN_STATE_TRANSITIONS.c.fan_id == normalized,
                    )
                )
                .order_by(desc(FAN_STATE_TRANSITIONS.c.created_at))
                .limit(30)
            ).mappings().all()
            callbacks = connection.execute(
                select(FAN_CALLBACKS)
                .where(
                    and_(
                        FAN_CALLBACKS.c.creator_id == self.creator_id,
                        FAN_CALLBACKS.c.fan_id == normalized,
                    )
                )
                .order_by(desc(FAN_CALLBACKS.c.current_relevance))
                .limit(20)
            ).mappings().all()
            memories = connection.execute(
                select(FAN_MEMORIES_V2)
                .where(
                    and_(
                        FAN_MEMORIES_V2.c.creator_id == self.creator_id,
                        FAN_MEMORIES_V2.c.fan_id == normalized,
                        FAN_MEMORIES_V2.c.status == "active",
                    )
                )
                .order_by(
                    desc(FAN_MEMORIES_V2.c.importance),
                    desc(FAN_MEMORIES_V2.c.last_confirmed_at),
                )
                .limit(40)
            ).mappings().all()
        return {
            "available": latest is not None,
            "relationship": dict(latest.get("relationship") or {}) if latest else {},
            "understanding": dict(latest.get("understanding") or {}) if latest else {},
            "strategy": dict(latest.get("strategy") or {}) if latest else {},
            "transitions": [
                {
                    "field_name": row["field_name"],
                    "new_value": row["new_value"],
                    "confidence": row["confidence"],
                    "reason_code": row["reason_code"],
                    "source_timestamp": row["source_timestamp"],
                    "shadow": bool(row["shadow"]),
                }
                for row in transitions
            ],
            "callbacks": [
                {
                    "subject": row["subject"],
                    "resolved": bool(row["resolved"]),
                    "emotional_sensitivity": row["emotional_sensitivity"],
                    "current_relevance": row["current_relevance"],
                    "earliest_safe_reuse_at": row["earliest_safe_reuse_at"],
                }
                for row in callbacks
            ],
            "facts": [
                {
                    "memory_type": row["memory_type"],
                    "memory_key": row["memory_key"],
                    "display_value": row["display_value"],
                    "confidence": row["confidence"],
                    "importance": row["importance"],
                    "contradiction_status": row["contradiction_status"],
                    "source_timestamp": row["source_timestamp"],
                }
                for row in memories
            ],
        }

    @staticmethod
    def _sanitize_run(row) -> dict:
        versions = dict(row.get("versions") or {})
        return {
            "id": int(row["id"]),
            "status": row["status"],
            "shadow": bool(row["shadow"]),
            "versions": versions,
            "strategy": dict(row.get("strategy") or {}),
            "delivery": dict(row.get("delivery") or {}),
            "rejection_codes": list(row.get("rejection_codes") or []),
            "candidate_count": len(row.get("candidate_fingerprints") or []),
            "selected_candidate_fingerprint": row.get(
                "selected_candidate_fingerprint"
            ),
            "model": row["model"],
            "model_calls": int(row["model_calls"] or 0),
            "latency_ms": int(row["latency_ms"] or 0),
            "estimated_cost": float(row["estimated_cost"] or 0.0),
            "created_at": row["created_at"],
        }
