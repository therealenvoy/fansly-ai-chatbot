"""Lightweight fan-style and semantic repetition utilities."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from statistics import mean


_WORD = re.compile(r"\b[\w']+\b", re.UNICODE)
_URL_OR_CODE = re.compile(
    r"(https?://\S+|www\.\S+|\b[A-Z0-9_-]{3,}\b)"
)
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF]",
    re.UNICODE,
)
_SERIOUS = re.compile(
    r"\b(sorry|hurt|hospital|death|died|anxious|panic|"
    r"uncomfortable|stop|boundary|unsafe|minor)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StyleFingerprint:
    lowercase_ratio: float
    average_length: float
    emoji_frequency: float
    question_frequency: float
    punctuation_density: float
    abbreviation_frequency: float
    sample_count: int

    def as_metrics(self) -> dict:
        return {
            "lowercase_ratio": round(self.lowercase_ratio, 4),
            "average_length": round(self.average_length, 2),
            "emoji_frequency": round(self.emoji_frequency, 4),
            "question_frequency": round(self.question_frequency, 4),
            "punctuation_density": round(self.punctuation_density, 4),
            "abbreviation_frequency": round(
                self.abbreviation_frequency,
                4,
            ),
        }


def fingerprint(messages: list[str]) -> StyleFingerprint:
    samples = [str(message) for message in messages if str(message).strip()][-50:]
    if not samples:
        return StyleFingerprint(0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    cased = [
        character
        for message in samples
        for character in message
        if character.isalpha()
    ]
    lowercase = (
        sum(character.islower() for character in cased) / len(cased)
        if cased
        else 0.5
    )
    words = [word.casefold() for message in samples for word in _WORD.findall(message)]
    abbreviations = {"u", "ur", "r", "rn", "idk", "imo", "tbh", "lol", "lmao"}
    return StyleFingerprint(
        lowercase_ratio=lowercase,
        average_length=mean(len(message) for message in samples),
        emoji_frequency=sum(len(_EMOJI.findall(message)) for message in samples)
        / len(samples),
        question_frequency=sum("?" in message for message in samples)
        / len(samples),
        punctuation_density=(
            sum(
                character in "!?.,;:"
                for message in samples
                for character in message
            )
            / max(1, sum(len(message) for message in samples))
        ),
        abbreviation_frequency=(
            sum(word in abbreviations for word in words) / max(1, len(words))
        ),
        sample_count=len(samples),
    )


def apply_casing(
    text: str,
    *,
    mode: str,
    fan_profile: StyleFingerprint | None = None,
) -> str:
    normalized = str(text or "").strip()
    if not normalized or mode in {"standard", "serious"}:
        return normalized
    if _SERIOUS.search(normalized):
        return normalized
    should_lower = mode == "mostly_lowercase"
    if mode == "mirror_fan":
        should_lower = bool(
            fan_profile
            and fan_profile.sample_count >= 3
            and fan_profile.lowercase_ratio >= 0.7
        )
    if not should_lower:
        return normalized
    protected: list[str] = []

    def protect(match):
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    lowered = _URL_OR_CODE.sub(protect, normalized).lower()
    for index, value in enumerate(protected):
        lowered = lowered.replace(f"\x00{index}\x00", value)
    return lowered


def semantic_signature(text: str) -> frozenset[str]:
    stop = {
        "a",
        "an",
        "and",
        "are",
        "i",
        "im",
        "is",
        "it",
        "of",
        "that",
        "the",
        "this",
        "to",
        "u",
        "ur",
        "you",
        "your",
    }
    tokens = [
        re.sub(r"(.)\1{2,}", r"\1\1", token.casefold())
        for token in _WORD.findall(str(text or ""))
    ]
    meaningful = [token for token in tokens if token not in stop]
    bigrams = {
        f"{meaningful[index]} {meaningful[index + 1]}"
        for index in range(len(meaningful) - 1)
    }
    return frozenset(set(meaningful) | bigrams)


def repetition_score(candidate: str, recent: list[str]) -> float:
    candidate_signature = semantic_signature(candidate)
    if not candidate_signature:
        return 0.0
    scores = []
    for message in recent[-20:]:
        other = semantic_signature(message)
        if not other:
            continue
        scores.append(
            len(candidate_signature & other)
            / max(1, len(candidate_signature | other))
        )
    return max(scores, default=0.0)


def apply_rare_typo(
    text: str,
    *,
    enabled: bool,
    seed: str,
) -> str:
    """Apply at most one deterministic, plausible typo to low-risk chat."""
    normalized = str(text or "")
    if not enabled or _SERIOUS.search(normalized):
        return normalized
    matches = [
        match
        for match in re.finditer(r"\b[a-z]{5,12}\b", normalized)
        if match.group(0) not in {"please", "sorry", "never", "always"}
    ]
    if not matches:
        return normalized
    digest = hashlib.sha256(
        f"{seed}\0{normalized}".encode("utf-8")
    ).digest()
    if digest[0] % 20 != 0:
        return normalized
    match = matches[digest[1] % len(matches)]
    word = match.group(0)
    index = 1 + digest[2] % (len(word) - 2)
    if word[index] == word[index + 1]:
        return normalized
    typo = (
        word[:index]
        + word[index + 1]
        + word[index]
        + word[index + 2 :]
    )
    return normalized[: match.start()] + typo + normalized[match.end() :]
