"""Per-fan and creator-wide structural repetition detection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from src.conversation.intelligence_v3.knowledge import tokenize


OPENING_WORDS = 5
PHRASE_WORDS = 4
PET_NAMES = {"babe", "baby", "sweetie", "cutie", "handsome", "love", "hun"}
TRANSITIONS = (
    "but now",
    "okay so",
    "tell me",
    "be honest",
    "come here",
    "that said",
    "wait",
)


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
    emoji_count = len(re.findall(r"[^\x00-\x7f]", value))
    has_ellipsis = "..." in value or chr(0x2026) in value
    return "|".join(
        (
            f"clauses:{len(clauses)}",
            f"question:{int('?' in value)}",
            f"ellipsis:{int(has_ellipsis)}",
            f"emoji:{emoji_count}",
            f"words:{min(len(_words(value)) // 5, 8)}",
        )
    )


def _digest(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _question_type(value: str) -> str:
    if "?" not in value:
        return "none"
    words = _words(value)
    for kind in ("why", "what", "how", "where", "when", "who", "which"):
        if kind in words:
            return kind
    return "yes_no"


def _semantic_cluster(value: str) -> str:
    lowered = value.casefold()
    clusters = (
        ("boundary_repair", r"\b(sorry|wrong|respect|space|back off)\b"),
        ("emotional_support", r"\b(hear you|with you|proud|hard|hurts|worry)\b"),
        ("playful", r"\b(tease|trouble|bold|confident|cute)\b"),
        ("explicit", r"\b(naked|horny|sex|fuck|cum|cock|pussy)\b"),
        ("curiosity", r"\b(tell me|what|how|why|which)\b"),
    )
    for name, pattern in clusters:
        if re.search(pattern, lowered):
            return name
    return "general"


def diversity_fingerprint(
    text: object,
    *,
    primary_act: str | None = None,
    secondary_act: str | None = None,
) -> dict:
    """Return content-free features suitable for durable diversity telemetry."""
    value = str(text or "").strip()
    words = _words(value)
    lowered = value.casefold()
    pet_names = sorted(set(words) & PET_NAMES)
    emojis = re.findall(r"[^\x00-\x7f]", value)
    transition = next((item for item in TRANSITIONS if item in lowered), "none")
    explicit = bool(re.search(r"\b(naked|horny|sex|fuck|cum|cock|pussy)\b", lowered))
    phrase_hashes = sorted(
        _digest(" ".join(gram))
        for gram in _ngrams(words, PHRASE_WORDS)
    )[:24]
    return {
        "message_sha256": _digest(value),
        "opener_sha256": _digest(" ".join(words[:OPENING_WORDS])),
        "phrase_hashes": phrase_hashes,
        "skeleton": structure_signature(value),
        "primary_act": str(primary_act or "unknown")[:32],
        "secondary_act": str(secondary_act or "none")[:32],
        "question_type": _question_type(value),
        "closing_sha256": _digest(" ".join(words[-OPENING_WORDS:])),
        "pet_name": pet_names[0] if pet_names else "none",
        "emoji_count": min(len(emojis), 4),
        "length_bucket": min(len(words) // 5, 12),
        "transition": transition,
        "explicit_phrasing": explicit,
        "semantic_cluster": _semantic_cluster(value),
    }


@dataclass(frozen=True)
class DiversityResult:
    approved: bool
    rejection_codes: tuple[str, ...]
    closest_similarity: float
    fingerprint: dict


class GlobalDiversityGate:
    """Fail closed on high-signal repeated text, openings, or skeletons."""

    def evaluate(
        self,
        candidate: str,
        *,
        recent_fan_messages: list[str],
        recent_creator_messages: list[str],
        creator_wide_messages: list[str] | None = None,
        primary_act: str | None = None,
        secondary_act: str | None = None,
    ) -> DiversityResult:
        candidate_words = _words(candidate)
        candidate_tokens = tokenize(candidate)
        candidate_ngrams = _ngrams(candidate_words, PHRASE_WORDS)
        candidate_opening = tuple(candidate_words[:OPENING_WORDS])
        signature = structure_signature(candidate)
        fingerprint = diversity_fingerprint(
            candidate,
            primary_act=primary_act,
            secondary_act=secondary_act,
        )
        reasons: set[str] = set()
        closest = 0.0
        for message in list(recent_fan_messages)[-30:]:
            words = _words(message)
            if not words:
                continue
            similarity = _jaccard(candidate_tokens, tokenize(message))
            closest = max(closest, similarity)
            phrase_overlap = _jaccard(
                candidate_ngrams,
                _ngrams(words, PHRASE_WORDS),
            )
            if similarity >= 0.9 or (
                len(candidate_ngrams) >= 2 and phrase_overlap >= 0.75
            ):
                reasons.add("copies_recent_fan_language")

        creator_recent = list(recent_creator_messages)[-30:]
        same_cluster_structure = 0
        for message in creator_recent:
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
            other = diversity_fingerprint(message)
            if (
                len(candidate_words) >= 8
                and fingerprint["closing_sha256"] == other["closing_sha256"]
            ):
                reasons.add("repeated_closing")
            if (
                fingerprint["transition"] != "none"
                and fingerprint["transition"] == other["transition"]
                and similarity >= 0.45
            ):
                reasons.add("repeated_transition")
            if (
                fingerprint["question_type"] != "none"
                and fingerprint["question_type"] == other["question_type"]
                and signature == other["skeleton"]
                and similarity >= 0.45
            ):
                reasons.add("repeated_question_pattern")
            if (
                fingerprint["pet_name"] != "none"
                and fingerprint["pet_name"] == other["pet_name"]
                and fingerprint["emoji_count"] == other["emoji_count"]
                and similarity >= 0.55
            ):
                reasons.add("repeated_petname_emoji_pattern")
            if (
                fingerprint["semantic_cluster"] == other["semantic_cluster"]
                and signature == other["skeleton"]
            ):
                same_cluster_structure += 1
        strict_cluster_limit = (
            5
            if str(primary_act or "") in {"support", "repair", "reassure", "give_space"}
            else 3
        )
        if same_cluster_structure >= strict_cluster_limit:
            reasons.add("repeated_semantic_cluster_structure")

        global_openers = 0
        global_patterns = 0
        global_petname_emoji = 0
        global_questions = 0
        for message in list(creator_wide_messages or [])[-500:]:
            words = _words(message)
            if not words:
                continue
            similarity = _jaccard(candidate_tokens, tokenize(message))
            closest = max(closest, similarity)
            other = diversity_fingerprint(message)
            if similarity >= 0.9:
                reasons.add("creator_wide_semantic_near_duplicate")
            if (
                len(candidate_words) >= OPENING_WORDS
                and candidate_opening == tuple(words[:OPENING_WORDS])
            ):
                global_openers += 1
            if (
                fingerprint["semantic_cluster"] == other["semantic_cluster"]
                and signature == other["skeleton"]
            ):
                global_patterns += 1
            if (
                fingerprint["pet_name"] != "none"
                and fingerprint["pet_name"] == other["pet_name"]
                and fingerprint["emoji_count"] == other["emoji_count"]
            ):
                global_petname_emoji += 1
            if (
                fingerprint["question_type"] != "none"
                and fingerprint["question_type"] == other["question_type"]
                and signature == other["skeleton"]
            ):
                global_questions += 1
        if global_openers >= 3:
            reasons.add("creator_wide_repeated_opener")
        if global_patterns >= 8:
            reasons.add("creator_wide_repeated_structure")
        if global_petname_emoji >= 10:
            reasons.add("creator_wide_petname_emoji_pattern")
        if global_questions >= 10:
            reasons.add("creator_wide_question_pattern")
        return DiversityResult(
            approved=not reasons,
            rejection_codes=tuple(sorted(reasons)),
            closest_similarity=round(closest, 4),
            fingerprint=fingerprint,
        )
