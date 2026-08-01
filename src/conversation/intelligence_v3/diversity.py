"""Per-fan and creator-wide structural repetition detection."""

from __future__ import annotations

from dataclasses import dataclass
import re

from src.conversation.intelligence_v3.knowledge import tokenize


OPENING_WORDS = 5
PHRASE_WORDS = 4


def _words(text: object) -> list[str]:
    return re.findall(r"[a-z0-9']+", str(text or "").lower())


def _ngrams(words: list[str], size: int) -> set[tuple[str, ...]]:
    return {
        tuple(words[index : index + size])
        for index in range(max(0, len(words) - size + 1))
    }


def _jaccard(left: set, right: set) -> float:
    return len(left & right) / max(1, len(left | right))


def structure_signature(text: object) -> str:
    value = str(text or "").strip()
    clauses = [part for part in re.split(r"[.!?\u2026]+", value) if part.strip()]
    return "|".join(
        (
            f"clauses:{len(clauses)}",
            f"question:{int('?' in value)}",
            f"ellipsis:{int('...' in value or chr(0x2026) in value)}",
            f"emoji:{len(re.findall(r'[^\x00-\x7f]', value))}",
            f"words:{min(len(_words(value)) // 5, 8)}",
        )
    )


@dataclass(frozen=True)
class DiversityResult:
    approved: bool
    rejection_codes: tuple[str, ...]
    closest_similarity: float


class GlobalDiversityGate:
    """Fail closed on high-signal repeated text, openings, or skeletons."""

    def evaluate(
        self,
        candidate: str,
        *,
        recent_fan_messages: list[str],
        recent_creator_messages: list[str],
    ) -> DiversityResult:
        candidate_words = _words(candidate)
        candidate_tokens = tokenize(candidate)
        candidate_ngrams = _ngrams(candidate_words, PHRASE_WORDS)
        candidate_opening = tuple(candidate_words[:OPENING_WORDS])
        signature = structure_signature(candidate)
        reasons: set[str] = set()
        closest = 0.0
        for message in list(recent_fan_messages)[-30:] + list(recent_creator_messages)[-500:]:
            words = _words(message)
            if not words:
                continue
            similarity = _jaccard(candidate_tokens, tokenize(message))
            closest = max(closest, similarity)
            if len(candidate_words) >= OPENING_WORDS and candidate_opening == tuple(words[:OPENING_WORDS]):
                reasons.add("repeated_opener")
            overlap = _jaccard(candidate_ngrams, _ngrams(words, PHRASE_WORDS))
            if len(candidate_ngrams) >= 2 and overlap >= 0.5:
                reasons.add("repeated_phrase")
            if similarity >= 0.82:
                reasons.add("semantic_near_duplicate")
            if len(candidate_words) >= 8 and signature == structure_signature(message):
                if similarity >= 0.45:
                    reasons.add("repeated_structure")
        return DiversityResult(
            approved=not reasons,
            rejection_codes=tuple(sorted(reasons)),
            closest_similarity=round(closest, 4),
        )
