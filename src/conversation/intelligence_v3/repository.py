"""Creator-scoped persistence for governed V3 knowledge and shadow evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import Counter
import hashlib
import json
import re
from typing import Iterable

from sqlalchemy import Integer, and_, case, desc, func, insert, or_, select, update

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
from src.human_delivery.schema import (
    CONVERSATION_DOCUMENTS,
    CONVERSATION_EXAMPLES,
    CREATOR_FACTS,
)
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

    def ingest(
        self,
        extracted: ExtractedDocument,
        *,
        actor: str = "operator",
        document_type: str = "conversation_playbook",
    ) -> dict:
        normalized_type = str(document_type or "conversation_playbook").strip().lower()
        if normalized_type not in {
            "conversation_playbook",
            "relationship_playbook",
            "sales_playbook",
            "principles",
            "decision_rules",
            "approved_examples",
            "boundaries",
        }:
            raise ValueError("invalid knowledge document type")
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
                            CONVERSATION_DOCUMENTS.c.document_type == normalized_type,
                        )
                    )
                ).scalar_one()
            ) + 1
            result = connection.execute(
                insert(CONVERSATION_DOCUMENTS).values(
                    creator_id=self.creator_id,
                    document_type=normalized_type,
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
        if values["knowledge_type"] not in {
            "principle",
            "decision_rule",
            "approved_example",
            "boundary",
        }:
            raise ValueError("invalid knowledge type")
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

    def set_document_status(
        self,
        document_id: int,
        *,
        status: str,
        actor: str,
    ) -> dict:
        """Activate or roll back one reviewed revision without deleting history."""
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"draft", "active", "archived"}:
            raise ValueError("invalid document status")
        now = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(CONVERSATION_DOCUMENTS).where(
                    and_(
                        CONVERSATION_DOCUMENTS.c.id == int(document_id),
                        CONVERSATION_DOCUMENTS.c.creator_id == self.creator_id,
                    )
                )
            ).mappings().first()
            if row is None:
                raise ValueError("knowledge document was not found")
            if normalized_status == "active":
                if str(row.get("extraction_status") or "") != "complete":
                    raise ValueError("review extraction quality before activation")
                connection.execute(
                    update(CONVERSATION_DOCUMENTS)
                    .where(
                        and_(
                            CONVERSATION_DOCUMENTS.c.creator_id == self.creator_id,
                            CONVERSATION_DOCUMENTS.c.document_type == row["document_type"],
                            CONVERSATION_DOCUMENTS.c.status == "active",
                            CONVERSATION_DOCUMENTS.c.id != int(document_id),
                        )
                    )
                    .values(status="archived", updated_at=now)
                )
            connection.execute(
                update(CONVERSATION_DOCUMENTS)
                .where(CONVERSATION_DOCUMENTS.c.id == int(document_id))
                .values(
                    status=normalized_status,
                    activated_at=now if normalized_status == "active" else row.get("activated_at"),
                    updated_at=now,
                )
            )
            updated = connection.execute(
                select(CONVERSATION_DOCUMENTS).where(
                    CONVERSATION_DOCUMENTS.c.id == int(document_id)
                )
            ).mappings().one()
        return dict(updated)

    def create_example(self, payload: dict, *, actor: str) -> dict:
        required = (
            "scenario",
            "stage",
            "fan_tone",
            "relationship_depth",
            "intended_act",
            "good_response",
        )
        values = {key: str(payload.get(key) or "").strip() for key in required}
        if any(not value for value in values.values()):
            raise ValueError("scenario, stage, tone, depth, act, and response are required")
        source_document_id = int(payload.get("source_document_id") or 0)
        source_page = int(payload.get("source_page") or 0)
        if source_document_id <= 0 or source_page <= 0:
            raise ValueError("a source document and page are required")
        status = str(payload.get("status") or "draft").strip().lower()
        if status not in {"draft", "active", "archived"}:
            raise ValueError("invalid example status")
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
            result = connection.execute(
                insert(CONVERSATION_EXAMPLES).values(
                    creator_id=self.creator_id,
                    stage=values["stage"][:64],
                    fan_tone=values["fan_tone"][:64],
                    relationship_depth=values["relationship_depth"][:64],
                    intended_act=values["intended_act"][:64],
                    good_response=values["good_response"][:2_000],
                    language=str(payload.get("language") or "en")[:16],
                    anti_example=str(payload.get("anti_example") or "")[:2_000] or None,
                    explanation=str(payload.get("explanation") or "")[:2_000] or None,
                    safety_class="conversation_only",
                    status=status,
                    revision=1,
                    scenario=values["scenario"][:128],
                    conversation_context=str(payload.get("conversation_context") or "")[:4_000] or None,
                    fan_state=dict(payload.get("fan_state") or {}),
                    source_document_id=source_document_id,
                    source_page=source_page,
                    reviewer=str(actor)[:64] if status == "active" else None,
                    reviewed_at=now if status == "active" else None,
                    created_at=now,
                    updated_at=now,
                )
            )
            row = connection.execute(
                select(CONVERSATION_EXAMPLES).where(
                    CONVERSATION_EXAMPLES.c.id == int(result.inserted_primary_key[0])
                )
            ).mappings().one()
        return dict(row)

    def set_example_status(self, example_id: int, *, status: str, actor: str) -> dict:
        normalized = str(status or "").strip().lower()
        if normalized not in {"draft", "active", "archived"}:
            raise ValueError("invalid example status")
        now = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(CONVERSATION_EXAMPLES).where(
                    and_(
                        CONVERSATION_EXAMPLES.c.id == int(example_id),
                        CONVERSATION_EXAMPLES.c.creator_id == self.creator_id,
                    )
                )
            ).mappings().first()
            if row is None:
                raise ValueError("example was not found")
            connection.execute(
                update(CONVERSATION_EXAMPLES)
                .where(CONVERSATION_EXAMPLES.c.id == int(example_id))
                .values(
                    status=normalized,
                    reviewer=str(actor)[:64],
                    reviewed_at=now,
                    updated_at=now,
                )
            )
            updated = connection.execute(
                select(CONVERSATION_EXAMPLES).where(
                    CONVERSATION_EXAMPLES.c.id == int(example_id)
                )
            ).mappings().one()
        return dict(updated)

    def retrieve(
        self,
        *,
        query: str,
        relationship_stage: str,
        scenario: str | None = None,
        profiles: Iterable[str] = ("conversation", "relationship"),
        rule_limit: int = 6,
        example_limit: int = 4,
    ) -> dict:
        profile_set = {str(value) for value in profiles}
        if "sales" in profile_set:
            profile_set.remove("sales")
        normalized_scenario = str(scenario or "").strip()[:128]
        terms = tokenize(query, relationship_stage, normalized_scenario)
        base_predicate = and_(
            CONVERSATION_KNOWLEDGE_RULES.c.creator_id == self.creator_id,
            CONVERSATION_KNOWLEDGE_RULES.c.status == "active",
            CONVERSATION_KNOWLEDGE_RULES.c.knowledge_profile.in_(profile_set),
        )
        with self.engine.connect() as connection:
            boundary_rows = connection.execute(
                select(CONVERSATION_KNOWLEDGE_RULES)
                .where(
                    and_(
                        base_predicate,
                        CONVERSATION_KNOWLEDGE_RULES.c.knowledge_type
                        == "boundary",
                    )
                )
                .order_by(desc(CONVERSATION_KNOWLEDGE_RULES.c.priority))
                .limit(12)
            ).mappings().all()
            rule_rows: list[dict] = []
            fts_terms = sorted(
                {
                    normalized
                    for term in terms
                    if len(normalized := re.sub(r"[^a-z0-9]", "", term)) >= 2
                }
            )[:24]
            if self.engine.dialect.name == "postgresql" and fts_terms:
                vector = func.to_tsvector(
                    "simple",
                    func.coalesce(CONVERSATION_KNOWLEDGE_RULES.c.search_text, ""),
                )
                # TOKEN_RE makes this expression safe for to_tsquery while OR
                # semantics preserve recall for short, informal fan messages.
                tsquery = func.to_tsquery("simple", " | ".join(fts_terms))
                rank = func.ts_rank_cd(vector, tsquery)
                matched = connection.execute(
                    select(CONVERSATION_KNOWLEDGE_RULES)
                    .add_columns(rank.label("_fts_rank"))
                    .where(
                        and_(
                            base_predicate,
                            CONVERSATION_KNOWLEDGE_RULES.c.knowledge_type
                            != "boundary",
                            vector.op("@@")(tsquery),
                        )
                    )
                    .order_by(
                        rank.desc(),
                        desc(CONVERSATION_KNOWLEDGE_RULES.c.priority),
                    )
                    .limit(24)
                ).mappings().all()
                rule_rows.extend(dict(row) for row in matched)

            # Structured fallback keeps sparse playbooks useful when the fan's
            # wording and the approved rule wording share no lexical token.
            # It remains bounded and never pulls sales rules into replies.
            if self.engine.dialect.name != "postgresql" or len(rule_rows) < rule_limit:
                matched_ids = [int(row["id"]) for row in rule_rows]
                fallback_query = (
                    select(CONVERSATION_KNOWLEDGE_RULES)
                    .where(
                        and_(
                            base_predicate,
                            CONVERSATION_KNOWLEDGE_RULES.c.knowledge_type
                            != "boundary",
                        )
                    )
                    .order_by(
                        desc(
                            case(
                                (
                                    CONVERSATION_KNOWLEDGE_RULES.c.scenario
                                    == normalized_scenario,
                                    2,
                                ),
                                (
                                    CONVERSATION_KNOWLEDGE_RULES.c.scenario
                                    == "all",
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        desc(CONVERSATION_KNOWLEDGE_RULES.c.priority),
                        desc(CONVERSATION_KNOWLEDGE_RULES.c.updated_at),
                    )
                    .limit(24)
                )
                if matched_ids:
                    fallback_query = fallback_query.where(
                        CONVERSATION_KNOWLEDGE_RULES.c.id.not_in(matched_ids)
                    )
                fallback = connection.execute(fallback_query).mappings().all()
                rule_rows.extend(dict(row) for row in fallback)
            example_rows = connection.execute(
                select(CONVERSATION_EXAMPLES).where(
                    and_(
                        CONVERSATION_EXAMPLES.c.creator_id == self.creator_id,
                        CONVERSATION_EXAMPLES.c.status == "active",
                        CONVERSATION_EXAMPLES.c.safety_class == "conversation_only",
                    )
                )
            ).mappings().all()
        normalized_rules = [dict(row) for row in rule_rows]
        boundaries = sorted(
            (dict(row) for row in boundary_rows),
            key=lambda row: (
                int(row.get("priority") or 0),
                float(row.get("_fts_rank") or 0.0),
            ),
            reverse=True,
        )[:12]
        rules = sorted(
            (
                row
                for row in normalized_rules
                if str(row.get("knowledge_type")) != "boundary"
            ),
            key=lambda row: (
                str(row.get("scenario") or "") == normalized_scenario,
                str(row.get("scenario") or "") == "all",
                relationship_stage in list(row.get("relationship_stages") or []),
                float(row.get("_fts_rank") or 0.0),
                lexical_score(terms, row.get("search_text")),
                int(row.get("priority") or 0),
            ),
            reverse=True,
        )[: max(1, min(int(rule_limit), 6))]
        ranked_examples = sorted(
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
        )
        examples: list[dict] = []
        structures: set[tuple[int, int, int]] = set()
        for row in ranked_examples:
            response = str(row.get("good_response") or "")
            signature = (
                int("?" in response),
                min(len(response.split()) // 6, 6),
                min(response.count(".") + response.count("!") + response.count("?"), 5),
            )
            if signature in structures:
                continue
            structures.add(signature)
            examples.append(row)
            if len(examples) >= max(1, min(int(example_limit), 4)):
                break
        return {
            "rules": rules,
            "boundaries": boundaries,
            "examples": examples,
            "fingerprint": _fingerprint(
                {
                    "rules": [(row["id"], row["version"]) for row in rules],
                    "boundaries": [
                        (row["id"], row["version"]) for row in boundaries
                    ],
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
            examples = connection.execute(
                select(CONVERSATION_EXAMPLES)
                .where(CONVERSATION_EXAMPLES.c.creator_id == self.creator_id)
                .order_by(desc(CONVERSATION_EXAMPLES.c.updated_at))
                .limit(100)
            ).mappings().all()
        return {
            "documents": [self._sanitize_document(row) for row in documents],
            "rules": [self._sanitize_rule(row) for row in rules],
            "open_conflicts": len(conflicts),
            "conflicts": [self._sanitize_conflict(row) for row in conflicts],
            "examples": [self._sanitize_example(row) for row in examples],
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

    @staticmethod
    def _sanitize_example(row) -> dict:
        item = dict(row)
        item.pop("good_response", None)
        item.pop("anti_example", None)
        item.pop("conversation_context", None)
        return item


class IntelligenceRepository:
    """Store evidence changes and privacy-safe V3 shadow telemetry."""

    def __init__(self, engine, *, creator_id: str):
        self.engine = engine
        self.creator_id = creator_id

    def verified_creator_facts(self, *, limit: int = 24) -> list[dict]:
        """Return source-backed creator facts only; never infer persona facts."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(CREATOR_FACTS)
                .where(
                    and_(
                        CREATOR_FACTS.c.creator_id == self.creator_id,
                        CREATOR_FACTS.c.status == "active",
                        CREATOR_FACTS.c.source_document_id.is_not(None),
                        CREATOR_FACTS.c.confidence >= 0.8,
                    )
                )
                .order_by(
                    desc(CREATOR_FACTS.c.confidence),
                    desc(CREATOR_FACTS.c.last_confirmed_at),
                )
                .limit(max(1, min(int(limit), 40)))
            ).mappings().all()
        return [
            {
                "fact_key": str(row["fact_key"])[:128],
                "fact_value": str(row["fact_value"])[:500],
                "confidence": round(float(row["confidence"]), 4),
                "source_document_id": int(row["source_document_id"]),
            }
            for row in rows
        ]

    def record_transition(
        self,
        *,
        fan_id: str,
        transition: dict,
        shadow: bool = True,
    ) -> bool:
        values = {
            "creator_id": self.creator_id,
            "fan_id": fan_id,
            "shadow": bool(shadow),
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

    def overlay_state(
        self,
        *,
        fan_id: str,
        base: dict | None = None,
        shadow: bool,
    ) -> dict:
        """Reconstruct one isolated V3 state overlay."""
        state = dict(base or {})
        aliases = {
            "current_emotion": state.get("current_mood"),
            "active_topic": state.get("active_thread"),
            "openness": state.get("openness_estimate"),
            "uncertainty": state.get("uncertainty_estimate"),
        }
        state.update({key: value for key, value in aliases.items() if value is not None})
        latest_ids = (
            select(func.max(FAN_STATE_TRANSITIONS.c.id))
            .where(
                and_(
                    FAN_STATE_TRANSITIONS.c.creator_id == self.creator_id,
                    FAN_STATE_TRANSITIONS.c.fan_id == fan_id,
                    FAN_STATE_TRANSITIONS.c.shadow.is_(bool(shadow)),
                )
            )
            .group_by(FAN_STATE_TRANSITIONS.c.field_name)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(FAN_STATE_TRANSITIONS).where(
                    FAN_STATE_TRANSITIONS.c.id.in_(latest_ids)
                )
            ).mappings().all()
        for row in rows:
            state[str(row["field_name"])] = row["new_value"]
        if rows:
            latest = max(
                rows,
                key=lambda row: (_aware(row["source_timestamp"]), int(row["id"])),
            )
            state["last_source_message_id"] = latest["source_message_id"]
            state["last_source_timestamp"] = latest["source_timestamp"]
            state["version"] = max(int(row["state_version"]) for row in rows)
        else:
            state["version"] = int(state.get("state_version") or 0)
        return state

    def shadow_state(self, *, fan_id: str, base: dict | None = None) -> dict:
        return self.overlay_state(fan_id=fan_id, base=base, shadow=True)

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

    def mark_callback_used(
        self,
        *,
        fan_id: str,
        callback_id: int,
        used_at: datetime,
    ) -> bool:
        """Apply a durable cooldown only to a callback explicitly selected by V3."""
        used_at = _aware(used_at)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(FAN_CALLBACKS).where(
                    and_(
                        FAN_CALLBACKS.c.id == int(callback_id),
                        FAN_CALLBACKS.c.creator_id == self.creator_id,
                        FAN_CALLBACKS.c.fan_id == fan_id,
                        FAN_CALLBACKS.c.resolved.is_(False),
                    )
                )
            ).mappings().first()
            if row is None:
                return False
            sensitive = str(row["emotional_sensitivity"]) != "standard"
            connection.execute(
                update(FAN_CALLBACKS)
                .where(FAN_CALLBACKS.c.id == int(callback_id))
                .values(
                    last_used_at=used_at,
                    times_referenced=int(row["times_referenced"] or 0) + 1,
                    earliest_safe_reuse_at=used_at
                    + timedelta(days=30 if sensitive else 7),
                    current_relevance=max(
                        0.1,
                        float(row["current_relevance"] or 0.5) * 0.6,
                    ),
                    updated_at=utcnow(),
                )
            )
        return True

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
                connection.execute(
                    update(CONVERSATION_INTELLIGENCE_RUNS)
                    .where(
                        and_(
                            CONVERSATION_INTELLIGENCE_RUNS.c.id
                            == int(existing),
                            CONVERSATION_INTELLIGENCE_RUNS.c.creator_id
                            == self.creator_id,
                        )
                    )
                    .values(
                        **{
                            key: value
                            for key, value in values.items()
                            if key not in {"creator_id", "created_at"}
                        }
                    )
                )
                return int(existing)
            result = connection.execute(
                insert(CONVERSATION_INTELLIGENCE_RUNS).values(**values)
            )
        return int(result.inserted_primary_key[0])

    def link_run_decision(
        self,
        *,
        run_id: int,
        decision_id: int,
        shadow: bool,
    ) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(CONVERSATION_INTELLIGENCE_RUNS)
                .where(
                    and_(
                        CONVERSATION_INTELLIGENCE_RUNS.c.id == int(run_id),
                        CONVERSATION_INTELLIGENCE_RUNS.c.creator_id
                        == self.creator_id,
                        CONVERSATION_INTELLIGENCE_RUNS.c.shadow.is_(
                            bool(shadow)
                        ),
                    )
                )
                .values(current_decision_id=int(decision_id))
            )
        return bool(result.rowcount)

    def live_cost_since(self, since: datetime) -> float:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(
                    func.coalesce(
                        func.sum(CONVERSATION_INTELLIGENCE_RUNS.c.estimated_cost),
                        0.0,
                    )
                ).where(
                    and_(
                        CONVERSATION_INTELLIGENCE_RUNS.c.creator_id
                        == self.creator_id,
                        CONVERSATION_INTELLIGENCE_RUNS.c.shadow.is_(False),
                        CONVERSATION_INTELLIGENCE_RUNS.c.created_at >= since,
                    )
                )
            ).scalar_one()
        return float(value or 0.0)

    def record_feedback(self, payload: dict, *, reviewer: str) -> int:
        allowed_types = {
            "good",
            "bad",
            "too_generic",
            "repetitive",
            "wrong_context",
            "wrong_tone",
            "too_long",
            "too_sexual",
            "missed_question",
            "memory_error",
            "operator_edited",
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
            attributed_outcomes = CONVERSATION_OUTCOMES.join(
                CONVERSATION_INTELLIGENCE_RUNS,
                and_(
                    CONVERSATION_OUTCOMES.c.conversation_decision_id
                    == CONVERSATION_INTELLIGENCE_RUNS.c.current_decision_id,
                    CONVERSATION_OUTCOMES.c.creator_id
                    == CONVERSATION_INTELLIGENCE_RUNS.c.creator_id,
                ),
            )
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
                    func.coalesce(
                        func.sum(
                            func.cast(CONVERSATION_OUTCOMES.c.correction_signal, Integer)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            func.cast(CONVERSATION_OUTCOMES.c.boundary_signal, Integer)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            func.cast(
                                CONVERSATION_OUTCOMES.c.manual_creator_takeover,
                                Integer,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            func.cast(
                                CONVERSATION_OUTCOMES.c.continued_three_turns,
                                Integer,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            func.cast(
                                CONVERSATION_OUTCOMES.c.returned_within_24h,
                                Integer,
                            )
                        ),
                        0,
                    ),
                    func.avg(CONVERSATION_OUTCOMES.c.reply_latency_seconds),
                    func.avg(CONVERSATION_OUTCOMES.c.disclosure_depth),
                )
                .select_from(attributed_outcomes)
                .where(
                    CONVERSATION_INTELLIGENCE_RUNS.c.creator_id == self.creator_id
                )
            ).one()
        outcome_count = int(outcome_row[0] or 0)
        fingerprints = [
            item
            for row in runs
            for item in list(row.get("candidate_fingerprints") or [])
            if isinstance(item, dict)
        ]
        opener_counts = Counter(
            item.get("opener_sha256") for item in fingerprints if item.get("opener_sha256")
        )
        skeleton_counts = Counter(
            item.get("skeleton") for item in fingerprints if item.get("skeleton")
        )
        act_counts = Counter(
            str((row.get("strategy") or {}).get("primary_act") or "unknown")
            for row in runs
        )
        question_counts = Counter(
            str(item.get("question_type") or "none") for item in fingerprints
        )
        pet_counts = Counter(str(item.get("pet_name") or "none") for item in fingerprints)
        emoji_counts = Counter(str(item.get("emoji_count") or 0) for item in fingerprints)
        fallback_runs = sum(
            1
            for row in runs
            if str(row.get("status") or "") in {"grounded_fallback", "operator_review_required"}
        )
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
                "correction_signals": int(outcome_row[6] or 0),
                "boundary_signals": int(outcome_row[7] or 0),
                "manual_takeovers": int(outcome_row[8] or 0),
                "continued_three_turns": int(outcome_row[9] or 0),
                "returned_within_24h": int(outcome_row[10] or 0),
                "average_reply_latency_seconds": (
                    round(float(outcome_row[11]), 2)
                    if outcome_row[11] is not None
                    else None
                ),
                "average_disclosure_depth": (
                    round(float(outcome_row[12]), 4)
                    if outcome_row[12] is not None
                    else None
                ),
            },
            "diversity": {
                "candidate_sample": len(fingerprints),
                "repeated_opener_clusters": sum(1 for value in opener_counts.values() if value > 1),
                "repeated_structure_clusters": sum(1 for value in skeleton_counts.values() if value > 1),
                "act_distribution": dict(act_counts),
                "question_type_distribution": dict(question_counts),
                "pet_name_distribution": dict(pet_counts),
                "emoji_count_distribution": dict(emoji_counts),
                "fallback_rate": round(fallback_runs / max(1, len(runs)), 4),
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
                    "id": int(row["id"]),
                    "memory_type": row["memory_type"],
                    "memory_key": row["memory_key"],
                    "display_value": row["display_value"],
                    "confidence": row["confidence"],
                    "importance": row["importance"],
                    "status": row["status"],
                    "sensitivity_class": row["sensitivity_class"],
                    "contradiction_status": row["contradiction_status"],
                    "source_timestamp": row["source_timestamp"],
                    "expires_at": row["expires_at"],
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
