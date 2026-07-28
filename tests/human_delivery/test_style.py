from src.human_delivery.style import (
    apply_casing,
    apply_rare_typo,
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


def test_typos_are_off_by_default_deterministic_and_skip_serious_text():
    text = "that sounds really amazing"
    assert apply_rare_typo(text, enabled=False, seed="1") == text
    changed = next(
        (
            apply_rare_typo(text, enabled=True, seed=str(seed))
            for seed in range(500)
            if apply_rare_typo(text, enabled=True, seed=str(seed)) != text
        ),
        None,
    )
    assert changed is not None
    seed = next(
        str(value)
        for value in range(500)
        if apply_rare_typo(text, enabled=True, seed=str(value)) == changed
    )
    assert apply_rare_typo(text, enabled=True, seed=seed) == changed
    serious = "sorry you feel unsafe, please stop"
    assert apply_rare_typo(serious, enabled=True, seed="1") == serious
