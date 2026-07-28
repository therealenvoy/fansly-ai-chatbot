"""Versioned document linting and explicit-budget prompt compilation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Iterable


DOCUMENT_TYPES = frozenset(
    {
        "creator_persona",
        "brand_bible",
        "conversation_guide",
        "sales_playbook",
    }
)
DOCUMENT_PRECEDENCE = (
    "creator_persona",
    "brand_bible",
    "conversation_guide",
    "sales_playbook",
)


@dataclass(frozen=True)
class LintFinding:
    code: str
    severity: str
    document_type: str
    summary: str


@dataclass(frozen=True)
class PromptCompilation:
    prompt: str
    fingerprint: str
    included: tuple[str, ...]
    excluded: tuple[dict, ...]
    character_count: int
    budget: int

    def safe_report(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "included": list(self.included),
            "excluded": [dict(item) for item in self.excluded],
            "character_count": self.character_count,
            "budget": self.budget,
        }


def _chunks(document_type: str, content: str) -> list[tuple[str, str]]:
    """Split at headings and paragraphs without silently cutting content."""
    normalized = str(content or "").strip()
    if not normalized:
        return []
    chunks: list[tuple[str, str]] = []
    heading = "General"
    body: list[str] = []
    for raw_line in normalized.splitlines():
        line = raw_line.rstrip()
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            if body:
                text = "\n".join(body).strip()
                if text:
                    chunks.append((heading, text))
            heading = match.group(1).strip()[:120]
            body = []
            continue
        if not line.strip() and body:
            text = "\n".join(body).strip()
            if text:
                chunks.append((heading, text))
            body = []
            continue
        body.append(line)
    if body:
        text = "\n".join(body).strip()
        if text:
            chunks.append((heading, text))
    return [
        (f"{document_type}:{index}:{heading}", text)
        for index, (heading, text) in enumerate(chunks, start=1)
    ]


class DocumentLinter:
    """Deterministic warnings; never mutates source documents."""

    _SALES = re.compile(
        r"\b(ppv|paywall|paid\s+message|price|discount|unlock|tip|"
        r"upsell|purchase|buy\s+this)\b",
        re.IGNORECASE,
    )
    _PRESSURE = re.compile(
        r"\b(fake\s+(?:discount|scarcity)|make\s+him\s+feel\s+guilty|"
        r"guilt\s+him|emotional\s+debt|make\s+him\s+dependent|"
        r"punish\s+him|withdraw\s+affection)\b",
        re.IGNORECASE,
    )
    _QUESTION_QUOTA = re.compile(
        r"\b(always|every\s+(?:reply|message)).{0,40}\b"
        r"(ask|question)\b",
        re.IGNORECASE,
    )
    _PET_RULE = re.compile(
        r"\b(always|never|do\s+not|don't)\b.{0,30}\b"
        r"(babe|baby|sweetie|handsome|cutie|pet\s+name)\b",
        re.IGNORECASE,
    )

    def lint(
        self,
        documents: dict[str, str],
        *,
        runtime_document_limit: int = 20_000,
    ) -> list[LintFinding]:
        findings: list[LintFinding] = []
        for document_type, raw in documents.items():
            content = str(raw or "")
            if not content.strip():
                findings.append(
                    LintFinding(
                        "missing_document",
                        "warning",
                        document_type,
                        "Document is empty; factual grounding may be incomplete.",
                    )
                )
                continue
            if len(content) > runtime_document_limit:
                findings.append(
                    LintFinding(
                        "legacy_runtime_truncation",
                        "error",
                        document_type,
                        (
                            f"Document has {len(content):,} characters and exceeds "
                            f"the legacy {runtime_document_limit:,}-character limit."
                        ),
                    )
                )
            if document_type != "sales_playbook" and self._SALES.search(content):
                findings.append(
                    LintFinding(
                        "sales_rules_mixed_into_conversation",
                        "error",
                        document_type,
                        "Sales or PPV language belongs in the inactive Sales Playbook.",
                    )
                )
            if self._PRESSURE.search(content):
                findings.append(
                    LintFinding(
                        "coercive_or_fabricated_pressure",
                        "error",
                        document_type,
                        "Document appears to encourage fabricated or coercive pressure.",
                    )
                )
            if self._QUESTION_QUOTA.search(content):
                findings.append(
                    LintFinding(
                        "forced_question_quota",
                        "warning",
                        document_type,
                        "A rigid question rule can make every reply feel like an interview.",
                    )
                )
            duplicate_lines = self._duplicate_lines(content)
            if duplicate_lines:
                findings.append(
                    LintFinding(
                        "duplicate_instructions",
                        "warning",
                        document_type,
                        f"{duplicate_lines} normalized instruction lines repeat.",
                    )
                )
        pet_rules = [
            match.group(0).casefold()
            for content in documents.values()
            for match in self._PET_RULE.finditer(str(content or ""))
        ]
        if any("never" in rule or "don't" in rule or "do not" in rule for rule in pet_rules) and any(
            "always" in rule for rule in pet_rules
        ):
            findings.append(
                LintFinding(
                    "contradictory_pet_name_rules",
                    "error",
                    "cross_document",
                    "The documents contain both mandatory and forbidden pet-name rules.",
                )
            )
        return findings

    @staticmethod
    def _duplicate_lines(content: str) -> int:
        seen: set[str] = set()
        duplicates = 0
        for line in content.splitlines():
            normalized = re.sub(r"\W+", " ", line.casefold()).strip()
            if len(normalized) < 24:
                continue
            if normalized in seen:
                duplicates += 1
            seen.add(normalized)
        return duplicates

    @staticmethod
    def serialize(findings: Iterable[LintFinding]) -> list[dict]:
        return [asdict(finding) for finding in findings]


class PromptCompiler:
    """Select complete prompt chunks under an explicit budget."""

    def __init__(self, *, budget: int = 30_000):
        self.budget = min(max(int(budget), 8_000), 60_000)

    def compile(
        self,
        *,
        runtime_rules: str,
        documents: dict[str, str],
        fan_memory: Iterable[str] = (),
        history: str = "",
        newest_turn: str = "",
        examples: Iterable[dict] = (),
        conversation_only: bool = True,
    ) -> PromptCompilation:
        included: list[str] = []
        excluded: list[dict] = []
        parts: list[str] = []
        used = 0

        def add(label: str, text: str, *, required: bool = False) -> None:
            nonlocal used
            block = f"\n\n[{label}]\n{str(text).strip()}".strip()
            if not block:
                return
            projected = used + len(block)
            if projected <= self.budget:
                parts.append(block)
                included.append(label)
                used = projected
                return
            excluded.append(
                {
                    "label": label,
                    "reason": (
                        "required_block_exceeds_budget"
                        if required
                        else "prompt_budget"
                    ),
                    "characters": len(block),
                }
            )

        add("runtime_rules", runtime_rules, required=True)
        for document_type in DOCUMENT_PRECEDENCE:
            if conversation_only and document_type == "sales_playbook":
                if str(documents.get(document_type, "")).strip():
                    excluded.append(
                        {
                            "label": document_type,
                            "reason": "conversation_only",
                            "characters": len(documents[document_type]),
                        }
                    )
                continue
            for label, text in _chunks(
                document_type,
                documents.get(document_type, ""),
            ):
                add(label, text)
        relevant_memory = [
            str(item).strip()
            for item in fan_memory
            if str(item).strip()
        ][:30]
        if relevant_memory:
            add(
                "relevant_fan_memory",
                "\n".join(f"- {item}" for item in relevant_memory),
            )
        if history.strip():
            add("recent_history", history)
        if newest_turn.strip():
            add("newest_fan_turn", newest_turn, required=True)
        for index, example in enumerate(list(examples)[:12], start=1):
            if not isinstance(example, dict):
                continue
            add(
                f"winning_example:{index}",
                "\n".join(
                    f"{key}: {value}"
                    for key, value in example.items()
                    if value not in (None, "", [], {})
                ),
            )
        prompt = "\n\n".join(parts)
        fingerprint = hashlib.sha256(
            prompt.encode("utf-8")
        ).hexdigest()
        return PromptCompilation(
            prompt=prompt,
            fingerprint=fingerprint,
            included=tuple(included),
            excluded=tuple(excluded),
            character_count=len(prompt),
            budget=self.budget,
        )
