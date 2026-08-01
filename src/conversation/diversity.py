"""Deterministic conversation-diversity analysis and example retrieval."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable, Mapping, TypeVar


_WORD = re.compile(r"\b[\w']+\b", re.UNICODE)
_FILLER_OPENERS = {
    "ah",
    "aww",
    "aw",
    "haha",
    "hehe",
    "hey",
    "mhm",
    "mm",
    "oh",
    "okay",
    "ok",
    "well",
}
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "for",
    "from",
    "i",
    "i'd",
    "i'm",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "this",
    "to",
    "u",
    "ur",
    "you",
    "your",
}
_ALIASES = {
    "n": "and",
    "u": "you",
    "ur": "your",
    "ya": "you",
}
_CONCEPT_PATTERNS = {
    "affection": re.compile(
        r"\b(?:kiss|kissing|hug|hugging|cuddle|cuddling|embrace)\w*\b",
        re.IGNORECASE,
    ),
    "closeness": re.compile(
        r"\b(?:hold|holding|close|closer|tight|tighter|arms?)\b|"
        r"\bjust\s+us\b|\bright\s+here\b|\bworld\s+fade",
        re.IGNORECASE,
    ),
    "continuation_prompt": re.compile(
        r"\bwhat\b.{0,28}\bnext\b|\btell\s+me\s+more\b|"
        r"\bthen\s+what\b",
        re.IGNORECASE,
    ),
    "comfort": re.compile(
        r"\b(?:rest|safe|easy|support|here\s+for\s+you|"
        r"here\s+for\s+u)\b",
        re.IGNORECASE,
    ),
    "validation": re.compile(
        r"\b(?:glad|proud|sweet|love\s+that|favorite|favourite)\b",
        re.IGNORECASE,
    ),
    "playful_challenge": re.compile(
        r"\b(?:bold|confident|trouble|tease|stealing|prove\s+it)\b",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class DiversityFingerprint:
    normalized: str
    opener: str | None
    signature: frozenset[str]
    phrases: frozenset[str]
    concepts: frozenset[str]


def _normalize_token(token: str) -> str:
    value = re.sub(r"(.)\1{2,}", r"\1\1", token.casefold())
    return _ALIASES.get(value, value)


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = normalized.replace("’", "'")
    return [_normalize_token(value) for value in _WORD.findall(normalized)]


def _meaningful(tokens: Iterable[str]) -> list[str]:
    return [value for value in tokens if value not in _STOP_WORDS]


def _phrase_set(tokens: list[str]) -> frozenset[str]:
    phrases: set[str] = set()
    for size in (2, 3, 4):
        for index in range(len(tokens) - size + 1):
            chunk = tokens[index : index + size]
            if all(value in _STOP_WORDS for value in chunk):
                continue
            phrases.add(" ".join(chunk))
    return frozenset(phrases)


def diversity_fingerprint(text: str) -> DiversityFingerprint:
    tokens = _tokens(text)
    meaningful = _meaningful(tokens)
    signature = set(meaningful)
    signature.update(
        f"{meaningful[index]} {meaningful[index + 1]}"
        for index in range(len(meaningful) - 1)
    )
    concepts = {
        name
        for name, pattern in _CONCEPT_PATTERNS.items()
        if pattern.search(str(text or ""))
    }
    signature.update(f"concept:{name}" for name in concepts)
    opener = tokens[0] if tokens and tokens[0] in _FILLER_OPENERS else None
    return DiversityFingerprint(
        normalized=" ".join(tokens),
        opener=opener,
        signature=frozenset(signature),
        phrases=_phrase_set(tokens),
        concepts=frozenset(concepts),
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def similarity(left: str, right: str) -> float:
    return _jaccard(
        diversity_fingerprint(left).signature,
        diversity_fingerprint(right).signature,
    )


def diversity_reason_codes(
    candidate: str,
    recent_creator_messages: Iterable[str],
) -> tuple[str, ...]:
    """Return stable codes for repeated wording and conversational templates."""
    current = diversity_fingerprint(candidate)
    recent = [
        diversity_fingerprint(value)
        for value in list(recent_creator_messages)[-20:]
        if str(value or "").strip()
    ]
    if not current.normalized or not recent:
        return ()

    codes: list[str] = []
    if current.opener and sum(
        item.opener == current.opener for item in recent[-8:]
    ) >= 2:
        codes.append("repeated_opener")

    for item in recent:
        shared_phrases = current.phrases & item.phrases
        if any(len(phrase.split()) >= 3 for phrase in shared_phrases):
            codes.append("repeated_phrase")
            break

    concept_pair_counts: Counter[tuple[str, str]] = Counter()
    for item in recent:
        shared_concepts = sorted(current.concepts & item.concepts)
        for left_index, left in enumerate(shared_concepts):
            for right in shared_concepts[left_index + 1 :]:
                concept_pair_counts[(left, right)] += 1
    # Broad concepts alone are not enough to reject a relevant continuation.
    # A template is stale only when the same pair of conversational moves has
    # already appeared at least twice in the recent creator turns.
    if any(count >= 2 for count in concept_pair_counts.values()):
        codes.append("repeated_template")

    if max(
        (_jaccard(current.signature, item.signature) for item in recent),
        default=0.0,
    ) >= 0.40:
        codes.append("semantic_repetition")
    return tuple(dict.fromkeys(codes))


def diversity_prompt_guidance(
    recent_creator_messages: Iterable[str],
) -> str:
    """Summarize overused forms without echoing full private messages."""
    fingerprints = [
        diversity_fingerprint(value)
        for value in list(recent_creator_messages)[-12:]
        if str(value or "").strip()
    ]
    if not fingerprints:
        return "Use a fresh opening and a conversational move suited to the newest turn."
    opener_counts = Counter(
        item.opener for item in fingerprints if item.opener
    )
    concept_counts = Counter(
        concept for item in fingerprints for concept in item.concepts
    )
    phrase_counts = Counter(
        phrase
        for item in fingerprints
        for phrase in item.phrases
        if 2 <= len(phrase.split()) <= 3
    )
    openings = sorted(
        value for value, count in opener_counts.items() if count >= 2
    )
    concepts = sorted(
        value for value, count in concept_counts.items() if count >= 2
    )
    phrases = sorted(
        (
            value
            for value, count in phrase_counts.items()
            if count >= 2
        ),
        key=lambda value: (-phrase_counts[value], value),
    )[:4]
    warnings: list[str] = []
    if openings:
        warnings.append("openings: " + ", ".join(openings))
    if concepts:
        warnings.append("conversational moves: " + ", ".join(concepts))
    if phrases:
        warnings.append("phrases: " + "; ".join(phrases))
    if not warnings:
        return "Use a fresh opening and a conversational move suited to the newest turn."
    return (
        "Do not reuse these recent patterns: "
        + " | ".join(warnings)
        + ". Choose a different opening, imagery, sentence shape, and conversational move."
    )


def select_diverse_texts(
    values: Iterable[str],
    *,
    query: str,
    recent_creator_messages: Iterable[str],
    limit: int = 4,
) -> list[str]:
    """Choose a small relevant set without teaching immediate repetition."""
    maximum = min(max(int(limit), 1), 6)
    recent = [
        str(value).strip()
        for value in recent_creator_messages
        if str(value).strip()
    ][-20:]
    query_signature = diversity_fingerprint(query).signature
    unique: list[tuple[int, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        text = str(raw or "").strip()
        key = diversity_fingerprint(text).normalized
        if not key or key in seen:
            continue
        seen.add(key)
        if max((similarity(text, item) for item in recent), default=0.0) >= 0.70:
            continue
        unique.append((index, text))

    ranked = sorted(
        unique,
        key=lambda item: (
            -_jaccard(
                diversity_fingerprint(item[1]).signature,
                query_signature,
            ),
            max(
                (similarity(item[1], value) for value in recent),
                default=0.0,
            ),
            item[0],
        ),
    )
    selected: list[str] = []
    for _, text in ranked:
        if max(
            (similarity(text, current) for current in selected),
            default=0.0,
        ) >= 0.65:
            continue
        selected.append(text)
        if len(selected) >= maximum:
            break
    return selected


_Record = TypeVar("_Record", bound=Mapping[str, object])


def select_diverse_records(
    records: Iterable[_Record],
    *,
    query: str,
    recent_creator_messages: Iterable[str],
    limit: int = 4,
    text_key: str = "good_response",
) -> list[_Record]:
    rows = list(records)
    selected_texts = select_diverse_texts(
        (str(row.get(text_key) or "") for row in rows),
        query=query,
        recent_creator_messages=recent_creator_messages,
        limit=limit,
    )
    by_key: dict[str, _Record] = {}
    for row in rows:
        key = diversity_fingerprint(str(row.get(text_key) or "")).normalized
        if key and key not in by_key:
            by_key[key] = row
    return [
        by_key[diversity_fingerprint(text).normalized]
        for text in selected_texts
    ]
