from src.human_delivery.style import (
    apply_casing,
    fingerprint,
    repetition_score,
)


def test_style_fingerprint_is_bounded_and_evidence_based():
    profile = fingerprint(["hey u 😊", "how r u?", "im good rn"])
    assert profile.sample_count == 3
    assert profile.lowercase_ratio > 0.9
    assert profile.abbreviation_frequency > 0
    assert profile.question_frequency > 0


def test_mostly_lowercase_preserves_urls_and_acronyms():
    assert apply_casing(
        "Hey NASA, See HTTPS://EXAMPLE.COM Now",
        mode="mostly_lowercase",
    ) == "hey NASA, see HTTPS://EXAMPLE.COM now"


def test_serious_content_is_not_forced_lowercase():
    text = "I am Sorry that happened. Please stop if uncomfortable."
    assert apply_casing(text, mode="mostly_lowercase") == text


def test_semantic_repetition_catches_template_reuse():
    score = repetition_score(
        "that actually made me smile",
        ["u seriously made me smile"],
    )
    assert score >= 0.25
    assert repetition_score(
        "rainy nights are my favorite",
        ["what did u eat today?"],
    ) == 0.0
