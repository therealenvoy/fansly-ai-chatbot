"""A/B Testing Engine — deterministic variant assignment and outcome tracking."""

import hashlib
from typing import Optional


class ABTestingEngine:
    """Deterministic A/B testing with hash-based variant assignment.

    Features:
    - Deterministic fan-to-variant mapping via MD5 hash.
    - Outcome recording and aggregated results.
    - Simple significance testing (20%+ relative improvement).
    - Winner promotion and test clearing.
    """

    def __init__(self):
        self._outcomes: dict[str, dict[str, list[bool]]] = {}

    def assign_variant(self, fan_id: str, test_name: str, variants: list[str]) -> str:
        """Assign a variant deterministically via hash.

        Args:
            fan_id: Unique fan identifier.
            test_name: Name of the test.
            variants: List of variant names.

        Returns:
            The assigned variant name.
        """
        key = f"{test_name}:{fan_id}"
        hash_val = int(hashlib.md5(key.encode()).hexdigest(), 16)
        index = hash_val % len(variants)
        return variants[index]

    def record_outcome(self, fan_id: str, test_name: str, variant: str, converted: bool) -> None:
        """Record a conversion outcome for a fan in a test.

        Args:
            fan_id: Unique fan identifier.
            test_name: Name of the test.
            variant: Variant the fan was assigned to.
            converted: Whether the fan converted.
        """
        if test_name not in self._outcomes:
            self._outcomes[test_name] = {}

        if variant not in self._outcomes[test_name]:
            self._outcomes[test_name][variant] = []

        self._outcomes[test_name][variant].append(converted)

    def get_results(self, test_name: str) -> dict:
        """Get aggregated results for a test.

        Args:
            test_name: Name of the test.

        Returns:
            Dict mapping variant -> {count, conversions, rate}.
        """
        if test_name not in self._outcomes:
            return {}

        results = {}
        for variant, outcomes in self._outcomes[test_name].items():
            count = len(outcomes)
            conversions = sum(1 for o in outcomes if o)
            rate = conversions / count if count > 0 else 0.0
            results[variant] = {
                "count": count,
                "conversions": conversions,
                "rate": rate,
            }
        return results

    def is_significant(self, test_name: str) -> bool:
        """Check if test results are significant.

        Significance is defined as the winner having at least 20%
        relative improvement over the loser.

        Args:
            test_name: Name of the test.

        Returns:
            True if significant, False otherwise.
        """
        results = self.get_results(test_name)
        if len(results) < 2:
            return False

        rates = [r["rate"] for r in results.values() if r["count"] > 0]
        if len(rates) < 2:
            return False

        max_rate = max(rates)
        min_rate = min(rates)

        if min_rate == 0.0:
            return max_rate > 0.0

        relative_improvement = (max_rate - min_rate) / min_rate
        return relative_improvement >= 0.20

    def promote_winner(self, test_name: str) -> str:
        """Return the winning variant name.

        Args:
            test_name: Name of the test.

        Returns:
            Name of the variant with the highest conversion rate.
        """
        results = self.get_results(test_name)
        if not results:
            return ""

        best_variant = max(results.items(), key=lambda kv: kv[1]["rate"])
        return best_variant[0]

    def clear_test(self, test_name: str) -> None:
        """Remove all data for a test.

        Args:
            test_name: Name of the test to clear.
        """
        self._outcomes.pop(test_name, None)
