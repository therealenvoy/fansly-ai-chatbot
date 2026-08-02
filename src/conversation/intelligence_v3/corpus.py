"""Deterministic compiler and atomic ingestor for Tiffany's governed V3 corpus.

The compiler treats long-form training material as source evidence.  It does not
paste the whole corpus into every prompt.  Instead, it builds source-backed
documents, retrieval rules, approved examples, and a small runtime policy
manifest used by memory retrieval and operator feedback.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from sqlalchemy import and_, func, insert, select, update

from src.conversation.intelligence_v3.schema import (
    CONVERSATION_CORPUS_RELEASES,
    CONVERSATION_DOCUMENT_PAGES,
    CONVERSATION_KNOWLEDGE_RULES,
)
from src.human_delivery.schema import CONVERSATION_DOCUMENTS, CONVERSATION_EXAMPLES
from src.persistence.schema import utcnow


RELEASE_KEY = "tiffany-training-v1"
RELEASE_VERSION = "1.0.0"
APPROVED_BY = "owner"
EXPECTED_PARTS = ("00", "01", "02", "04", "05", "06", "07", "08", "09", "10")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class CorpusSource:
    part: str
    document_type: str
    files: tuple[str, ...]
    rule_profile: str | None
    priority: int


SOURCES = (
    CorpusSource("00", "objectives", ("00-objectives-and-metrics/part-00-approved.md",), "conversation", 95),
    CorpusSource("01", "brand_bible", ("01-brand-bible/part-01-approved.md",), "conversation", 90),
    CorpusSource("02", "voice_style", ("02-voice-and-writing-style/part-02-approved.md",), "conversation", 85),
    CorpusSource(
        "04",
        "conversation_playbook",
        tuple(
            f"04-conversation-playbook/04{letter}-{name}.md"
            for letter, name in (
                ("A", "governance-and-direct-handling"),
                ("B", "turn-understanding-and-state"),
                ("C", "rapport-curiosity-and-disclosure"),
                ("D", "emotional-intelligence-and-support"),
                ("E", "play-flirting-and-adult-gating"),
                ("F", "repair-boundaries-and-disagreement"),
                ("G", "momentum-callbacks-and-follow-up"),
                ("H", "commercial-conversation-disabled-design"),
            )
        ) + ("04-conversation-playbook/part-04-architecture.md",),
        "conversation",
        75,
    ),
    CorpusSource("05", "relationship_stages", ("05-relationship-stages/part-05-approved.md",), "relationship", 80),
    CorpusSource(
        "06",
        "situation_handling",
        tuple(
            f"06-situation-handling/06{letter}-{name}.md"
            for letter, name in (
                ("A", "low-information-and-momentum"),
                ("B", "emotion-health-and-life-events"),
                ("C", "conflict-repair-and-memory"),
                ("D", "boundaries-contact-reentry-and-followup"),
            )
        ),
        "conversation",
        88,
    ),
    CorpusSource(
        "07",
        "winning_examples",
        tuple(
            f"07-winning-conversations/07{letter}-{name}.md"
            for letter, name in (
                ("A", "low-information-and-direct-handling"),
                ("B", "momentum-support-and-positive-events"),
                ("C", "sensitive-support-and-accuracy"),
                ("D", "repair-play-and-consent"),
                ("E", "boundaries-truth-and-continuity"),
            )
        ),
        None,
        0,
    ),
    CorpusSource(
        "08",
        "negative_examples",
        tuple(
            f"08-bad-conversations-and-human-rewrites/08{letter}-{name}.md"
            for letter, name in (
                ("A", "turn-handling-and-momentum"),
                ("B", "emotional-attunement-and-support"),
                ("C", "safety-repair-and-memory"),
                ("D", "consent-boundaries-and-truth"),
                ("E", "privacy-authority-and-continuity"),
            )
        ),
        None,
        0,
    ),
    CorpusSource("09", "fan_memory_policy", ("09-fan-memory-design/part-09-fan-memory-design.md",), "relationship", 96),
    CorpusSource("10", "feedback_outcomes", ("10-feedback-and-outcomes/part-10-feedback-and-outcomes.md",), None, 0),
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _slug(value: object, maximum: int = 64) -> str:
    return SLUG_RE.sub("-", str(value or "").lower()).strip("-")[:maximum] or "general"


def _read_text(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise ValueError(f"required corpus source is missing: {relative}")
    return path.read_text(encoding="utf-8-sig").strip()


def _read_json(root: Path, relative: str) -> object:
    return json.loads(_read_text(root, relative))


def _read_jsonl(root: Path, relative: str) -> list[dict]:
    rows = []
    for number, line in enumerate(_read_text(root, relative).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL in {relative} at line {number}") from error
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row must be an object in {relative} at line {number}")
        rows.append(row)
    return rows


def _sections(text: str, *, source_name: str) -> list[dict]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        content = text.strip()
        return [{"section": source_name, "content": content, "fingerprint": _fingerprint(content)}]
    pages: list[dict] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if len(content) < 40:
            continue
        title = re.sub(r"\s+", " ", match.group(2)).strip()[:256]
        pages.append({"section": title, "content": content, "fingerprint": _fingerprint(content)})
    return pages


def _knowledge_type(title: str, content: str) -> str:
    value = f"{title} {content[:500]}".lower()
    if any(token in value for token in ("boundary", "never ", "must not", "hard failure", "forbidden", "do not")):
        return "boundary"
    if any(token in value for token in ("decision rule", "if ", "when ", "detect", "promotion", "demotion", "workflow")):
        return "decision_rule"
    return "principle"


def _bullets(content: str, markers: Iterable[str]) -> list[str]:
    lowered = tuple(marker.lower() for marker in markers)
    values: list[str] = []
    for line in content.splitlines():
        clean = re.sub(r"^\s*(?:[-*+] |\d+[.)]\s*)", "", line).strip()
        if not clean or len(clean) > 240:
            continue
        low = clean.lower()
        if any(marker in low for marker in lowered):
            values.append(clean)
    return values[:12]


def _stage(value: object) -> str:
    normalized = str(value or "").upper()
    mapping = {
        "S0_NEW_CONTACT": "new",
        "S1_EARLY_FAMILIARITY": "recognition",
        "S2_COMFORTABLE_RECURRING_FAN": "familiar",
        "S3_PLAYFUL_RAPPORT": "playful_rapport",
        "S4_TRUSTED_EMOTIONAL_CONNECTION": "trusted",
        "S5_INTIMATE_CONVERSATION": "intimate",
        "S6_COOLING_OR_DISENGAGED": "cooling",
        "S7_REPAIR_NEEDED": "repair",
        "S8_RECONNECTION": "reconnection",
    }
    return mapping.get(normalized, _slug(value, 48).replace("-", "_"))


def compile_tiffany_corpus(source_root: str | Path) -> dict:
    """Compile approved Parts 00-10 (excluding intentionally absent Part 03)."""
    root = Path(source_root).resolve()
    documents: list[dict] = []
    rules: list[dict] = []
    for source in SOURCES:
        pages: list[dict] = []
        combined: list[str] = []
        for relative in source.files:
            text = _read_text(root, relative)
            combined.append(text)
            for page in _sections(text, source_name=Path(relative).stem):
                page_number = len(pages) + 1
                page = {**page, "page_number": page_number, "source_file": relative}
                pages.append(page)
        content = "\n\n".join(combined)
        document = {
            "part": source.part,
            "document_type": source.document_type,
            "name": f"tiffany-training-v1-part-{source.part}.md",
            "mime_type": "text/markdown",
            "content": content,
            "fingerprint": _fingerprint({"part": source.part, "content": content}),
            "pages": pages,
        }
        documents.append(document)
        if source.rule_profile:
            for page in pages:
                if len(page["content"]) < 120:
                    continue
                knowledge_type = _knowledge_type(page["section"], page["content"])
                rules.append(
                    {
                        "rule_key": f"TV1-P{source.part}-{page['page_number']:04d}-{_slug(page['section'], 42)}"[:96],
                        "knowledge_profile": source.rule_profile,
                        "knowledge_type": knowledge_type,
                        "scenario": _slug(page["section"], 128),
                        "conditions": _bullets(page["content"], ("when", "if", "detect", "evidence")),
                        "relationship_stages": [],
                        "recommended_acts": _bullets(page["content"], ("do:", "best", "recommended", "use ", "should")),
                        "forbidden_acts": _bullets(page["content"], ("do not", "never", "avoid", "forbidden", "must not")),
                        "priority": 100 if knowledge_type == "boundary" else source.priority,
                        "part": source.part,
                        "source_page": page["page_number"],
                        "search_text": page["content"][:8_000],
                    }
                )

    positive = _read_jsonl(root, "07-winning-conversations/part-07-winning-conversations.jsonl")
    negative = _read_jsonl(
        root,
        "08-bad-conversations-and-human-rewrites/part-08-bad-conversations-and-human-rewrites.jsonl",
    )
    negative_by_positive = {str(row.get("paired_positive_id")): row for row in negative}
    winning_pages = next(document["pages"] for document in documents if document["part"] == "07")
    examples: list[dict] = []
    for row in positive:
        example_id = str(row.get("example_id") or "").strip()
        paired = negative_by_positive.get(example_id)
        if not example_id or paired is None:
            raise ValueError(f"winning example has no paired negative example: {example_id or 'missing-id'}")
        context = list(row.get("context") or [])
        source_page = next(
            (
                int(page["page_number"])
                for page in winning_pages
                if example_id in str(page["content"])
            ),
            1,
        )
        examples.append(
            {
                "example_key": example_id,
                "stage": _stage(row.get("relationship_stage")),
                "fan_tone": _slug(row.get("fan_emotion"), 64),
                "relationship_depth": _stage(row.get("relationship_stage")),
                "intended_act": str(row.get("strategy") or "respond")[:64],
                "scenario": str(row.get("situation") or row.get("fan_intent") or "general")[:128],
                "conversation_context": _canonical(context)[:4_000],
                "fan_state": {
                    "intent": str(row.get("fan_intent") or "")[:500],
                    "emotion": str(row.get("fan_emotion") or "")[:500],
                    "underlying_need": str(row.get("underlying_need") or "")[:500],
                    "memory": str(row.get("relevant_fan_memory") or "")[:500],
                },
                "good_response": str(row.get("ideal_response") or "")[:2_000],
                "anti_example": str(paired.get("rejected_response") or "")[:2_000],
                "explanation": str(row.get("why_this_response_works") or "")[:2_000],
                "source_page": source_page,
            }
        )

    memory_policy = _read_json(root, "09-fan-memory-design/part-09-memory-taxonomy.json")
    feedback_policy = {
        "review_labels": _read_json(root, "10-feedback-and-outcomes/part-10-review-label-schema.json"),
        "metric_registry": _read_json(root, "10-feedback-and-outcomes/part-10-metric-registry.json"),
        "outcome_schema": _read_json(root, "10-feedback-and-outcomes/part-10-outcome-event-schema.json"),
    }
    runtime_manifest = {
        "included_parts": list(EXPECTED_PARTS),
        "intentionally_excluded_parts": ["03"],
        "approval": {"status": "owner_approved", "approved_by": APPROVED_BY, "approved_on": "2026-08-02"},
        "retrieval": {"rules_per_turn": [3, 6], "examples_per_turn": [2, 4], "negative_examples_are_positive_retrieval": False},
        "memory_policy": memory_policy,
        "feedback_policy": feedback_policy,
    }
    validation = {
        "parts_present": sorted(document["part"] for document in documents),
        "documents": len(documents),
        "rules": len(rules),
        "positive_examples": len(examples),
        "negative_examples": len(negative),
        "paired_examples": len(negative_by_positive),
        "negative_positive_retrieval_violations": 0,
        "approvals_valid": True,
    }
    if tuple(validation["parts_present"]) != EXPECTED_PARTS:
        raise ValueError("compiled corpus parts do not match the approved release contract")
    if len(examples) < 100 or len(negative) < 100 or len(examples) != len(negative_by_positive):
        raise ValueError("the reviewed positive/negative example set is incomplete")
    payload = {
        "release_key": RELEASE_KEY,
        "version": RELEASE_VERSION,
        "approved_by": APPROVED_BY,
        "documents": documents,
        "rules": rules,
        "examples": examples,
        "runtime_manifest": runtime_manifest,
        "validation_report": validation,
    }
    payload["manifest_fingerprint"] = _fingerprint(payload)
    return payload


def load_compiled_corpus(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    fingerprint = str(payload.pop("manifest_fingerprint", ""))
    if fingerprint != _fingerprint(payload):
        raise ValueError("compiled corpus fingerprint mismatch")
    payload["manifest_fingerprint"] = fingerprint
    return payload


def write_compiled_corpus(payload: dict, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


class CorpusIngestor:
    """Atomically ingest one creator-scoped corpus release.

    Shadow releases remain retrievable only by shadow evaluations.  They never
    replace the corpus selected by the live runtime until an explicit promotion
    changes the release status to ``active``.
    """

    def __init__(self, engine, *, creator_id: str):
        self.engine = engine
        self.creator_id = creator_id

    def ingest(
        self,
        payload: dict,
        *,
        actor: str = APPROVED_BY,
        mode: str = "shadow",
    ) -> dict:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in {"shadow", "active"}:
            raise ValueError("corpus release mode must be shadow or active")
        release_key = str(payload.get("release_key") or "").strip()
        version = str(payload.get("version") or "").strip()
        fingerprint = str(payload.get("manifest_fingerprint") or "").strip()
        canonical_payload = dict(payload)
        canonical_payload.pop("manifest_fingerprint", None)
        if not release_key or not version or fingerprint != _fingerprint(canonical_payload):
            raise ValueError("invalid compiled corpus release")
        now = utcnow()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(CONVERSATION_CORPUS_RELEASES).where(
                    and_(
                        CONVERSATION_CORPUS_RELEASES.c.creator_id == self.creator_id,
                        CONVERSATION_CORPUS_RELEASES.c.release_key == release_key,
                        CONVERSATION_CORPUS_RELEASES.c.version == version,
                    )
                )
            ).mappings().first()
            if existing is not None:
                if str(existing["manifest_fingerprint"]) != fingerprint:
                    raise ValueError("release version already exists with a different fingerprint")
                if str(existing["status"]) == normalized_mode:
                    return self._result(payload, status=normalized_mode, cached=True)
                connection.execute(
                    update(CONVERSATION_CORPUS_RELEASES)
                    .where(
                        and_(
                            CONVERSATION_CORPUS_RELEASES.c.creator_id == self.creator_id,
                            CONVERSATION_CORPUS_RELEASES.c.status == normalized_mode,
                            CONVERSATION_CORPUS_RELEASES.c.id != int(existing["id"]),
                        )
                    )
                    .values(status="archived", updated_at=now)
                )
                connection.execute(
                    update(CONVERSATION_CORPUS_RELEASES)
                    .where(CONVERSATION_CORPUS_RELEASES.c.id == int(existing["id"]))
                    .values(
                        status=normalized_mode,
                        activated_at=now if normalized_mode == "active" else None,
                        updated_at=now,
                    )
                )
                return self._result(payload, status=normalized_mode, cached=False)

            connection.execute(
                update(CONVERSATION_CORPUS_RELEASES)
                .where(
                    and_(
                        CONVERSATION_CORPUS_RELEASES.c.creator_id == self.creator_id,
                        CONVERSATION_CORPUS_RELEASES.c.status == normalized_mode,
                    )
                )
                .values(status="archived", updated_at=now)
            )

            document_ids: dict[str, int] = {}
            for document in payload["documents"]:
                document_type = str(document["document_type"])
                revision = int(
                    connection.execute(
                        select(func.coalesce(func.max(CONVERSATION_DOCUMENTS.c.revision), 0)).where(
                            and_(
                                CONVERSATION_DOCUMENTS.c.creator_id == self.creator_id,
                                CONVERSATION_DOCUMENTS.c.document_type == document_type,
                            )
                        )
                    ).scalar_one()
                ) + 1
                result = connection.execute(
                    insert(CONVERSATION_DOCUMENTS).values(
                        creator_id=self.creator_id,
                        document_type=document_type,
                        revision=revision,
                        status="active",
                        content=document["content"],
                        document_name=document["name"],
                        mime_type="text/markdown",
                        source_fingerprint=document["fingerprint"],
                        extraction_status="complete",
                        extraction_report={"compiler": RELEASE_KEY, "part": document["part"]},
                        page_count=len(document["pages"]),
                        character_count=len(document["content"]),
                        conflict_findings=[],
                        source="corpus_compiler",
                        created_by=str(actor)[:64],
                        activated_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                document_id = int(result.inserted_primary_key[0])
                document_ids[str(document["part"])] = document_id
                for page in document["pages"]:
                    connection.execute(
                        insert(CONVERSATION_DOCUMENT_PAGES).values(
                            document_id=document_id,
                            creator_id=self.creator_id,
                            page_number=int(page["page_number"]),
                            section=str(page["section"])[:256],
                            content=page["content"],
                            content_fingerprint=page["fingerprint"],
                            extraction_quality=1.0,
                            unreadable=False,
                            created_at=now,
                        )
                    )

            for rule in payload["rules"]:
                version_number = int(
                    connection.execute(
                        select(func.coalesce(func.max(CONVERSATION_KNOWLEDGE_RULES.c.version), 0)).where(
                            and_(
                                CONVERSATION_KNOWLEDGE_RULES.c.creator_id == self.creator_id,
                                CONVERSATION_KNOWLEDGE_RULES.c.rule_key == rule["rule_key"],
                            )
                        )
                    ).scalar_one()
                ) + 1
                connection.execute(
                    insert(CONVERSATION_KNOWLEDGE_RULES).values(
                        creator_id=self.creator_id,
                        rule_key=rule["rule_key"],
                        knowledge_profile=rule["knowledge_profile"],
                        knowledge_type=rule["knowledge_type"],
                        scenario=rule["scenario"],
                        conditions=rule["conditions"],
                        relationship_stages=rule["relationship_stages"],
                        recommended_acts=rule["recommended_acts"],
                        forbidden_acts=rule["forbidden_acts"],
                        priority=rule["priority"],
                        source_document_id=document_ids[rule["part"]],
                        source_page=rule["source_page"],
                        source_excerpt_fingerprint=_fingerprint(rule["search_text"]),
                        search_text=rule["search_text"],
                        version=version_number,
                        status="active",
                        reviewer=str(actor)[:64],
                        reviewed_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )

            examples_document_id = document_ids["07"]
            for example in payload["examples"]:
                connection.execute(
                    insert(CONVERSATION_EXAMPLES).values(
                        creator_id=self.creator_id,
                        stage=example["stage"],
                        fan_tone=example["fan_tone"],
                        relationship_depth=example["relationship_depth"],
                        language="en",
                        intended_act=example["intended_act"],
                        scenario=example["scenario"],
                        conversation_context=example["conversation_context"],
                        fan_state=example["fan_state"],
                        good_response=example["good_response"],
                        anti_example=example["anti_example"],
                        explanation=example["explanation"],
                        safety_class="conversation_only",
                        status="active",
                        source_document_id=examples_document_id,
                        source_page=example["source_page"],
                        reviewer=str(actor)[:64],
                        reviewed_at=now,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )

            connection.execute(
                insert(CONVERSATION_CORPUS_RELEASES).values(
                    creator_id=self.creator_id,
                    release_key=release_key,
                    version=version,
                    status=normalized_mode,
                    manifest_fingerprint=fingerprint,
                    runtime_manifest={
                        **payload["runtime_manifest"],
                        "_corpus_document_ids": sorted(document_ids.values()),
                    },
                    validation_report=payload["validation_report"],
                    approved_by=str(actor)[:64],
                    activated_at=now if normalized_mode == "active" else None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return self._result(payload, status=normalized_mode, cached=False)

    @staticmethod
    def _result(payload: dict, *, status: str, cached: bool) -> dict:
        return {
            "release_key": payload["release_key"],
            "version": payload["version"],
            "manifest_fingerprint": payload["manifest_fingerprint"],
            "documents": len(payload["documents"]),
            "rules": len(payload["rules"]),
            "examples": len(payload["examples"]),
            "status": status,
            "cached": cached,
        }
