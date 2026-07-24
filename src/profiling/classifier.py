"""Fan personality classification from early chat messages."""
from dataclasses import dataclass, field


@dataclass
class ClassificationResult:
    """Result of fan personality classification.

    Attributes:
        personality_type: One of instant_buyer, quiet_lurker, chatty_fan, tester, attention_seeker
        confidence: Float 0.0-1.0 indicating confidence in the classification
        evidence: List of strings explaining the classification reasoning
    """

    personality_type: str
    confidence: float
    evidence: list[str] = field(default_factory=list)


# Keyword patterns mapping personality types to indicator phrases
PATTERNS: dict[str, list[str]] = {
    "instant_buyer": ["ppv", "buy", "content", "video", "unlock", "price", "how much", "purchase"],
    "quiet_lurker": [],   # detected via brevity heuristics
    "attention_seeker": ["notice me", "reply", "please", "anyone there", "talk to me"],
    "tester": ["free", "discount", "why so much", "really?", "prove it", "sample"],
    "chatty_fan": [],     # detected via length + engagement heuristics
}

ALL_TYPES = list(PATTERNS.keys())


class FanClassifier:
    """Classifies a fan into one of 5 personality types from their first 2-3 messages.

    Uses keyword matching combined with message-length and engagement heuristics.
    """

    def classify(self, messages: list[str]) -> ClassificationResult:
        """Classify fan personality from a list of early messages.

        Args:
            messages: List of fan message strings (typically first 2-3).

        Returns:
            ClassificationResult with personality_type, confidence, and evidence.
        """
        if not messages:
            return ClassificationResult(
                personality_type="quiet_lurker",
                confidence=0.1,
                evidence=["no messages to classify; defaulting to quiet_lurker"],
            )

        # Combine all messages, lowercase
        combined = " ".join(messages).lower()

        # Score each type by keyword matches
        scores: dict[str, float] = {t: 0.0 for t in ALL_TYPES}
        evidence: list[str] = []

        for ptype, keywords in PATTERNS.items():
            for kw in keywords:
                if kw in combined:
                    # Weight multi-word phrases higher (more specific signal)
                    weight = float(len(kw.split()))
                    scores[ptype] += weight
                    evidence.append(f"keyword '{kw}' matched → {ptype} +{weight}")

        # Heuristic adjustments based on message properties
        total_chars = sum(len(m) for m in messages)
        avg_len = total_chars / len(messages)

        # Only apply quiet_lurker heuristic when no keywords matched —
        # prevents short attention_seeker/tester messages from being misclassified
        any_keyword_matched = any(s > 0 for s in scores.values())

        if avg_len < 10 and not any_keyword_matched:
            scores["quiet_lurker"] += 2.0
            evidence.append(f"avg message length {avg_len:.1f} < 10 → quiet_lurker +2")

        if avg_len > 80:
            scores["chatty_fan"] += 2.0
            evidence.append(f"avg message length {avg_len:.1f} > 80 → chatty_fan +2")

        if len(messages) > 2:
            scores["chatty_fan"] += 1.0
            scores["attention_seeker"] += 0.5
            evidence.append(
                f"message count {len(messages)} > 2 → chatty_fan +1, attention_seeker +0.5"
            )

        # Pick highest-scoring type
        best_type = max(ALL_TYPES, key=lambda t: scores[t])
        best_score = scores[best_type]
        total_scores = sum(scores.values())

        confidence = best_score / total_scores if total_scores > 0 else 0.0

        return ClassificationResult(
            personality_type=best_type,
            confidence=confidence,
            evidence=evidence,
        )