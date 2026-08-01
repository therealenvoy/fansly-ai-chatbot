from src.conversation.diversity import (
    diversity_reason_codes,
    diversity_prompt_guidance,
    select_diverse_records,
    select_diverse_texts,
)


def test_one_related_conversation_move_is_not_mistaken_for_a_template():
    reasons = diversity_reason_codes(
        "that kiss caught me off guard, u really know how to make an entrance",
        ["i'd kiss u softly and hold u close"],
    )

    assert "repeated_template" not in reasons


def test_text_example_selection_is_small_relevant_and_non_repetitive():
    examples = [
        "mm babe i'd hold u close",
        "mmm babe i'd hold u tighter",
        "history is wild, what era are u covering?",
        "which part of that class surprised u most?",
        "that sounds exhausting, take it easy tonight",
        "okayyy look at u, that is actually impressive",
    ]

    selected = select_diverse_texts(
        examples,
        query="my only summer class is history",
        recent_creator_messages=["mm babe i'd hold u close"],
        limit=4,
    )

    assert 1 <= len(selected) <= 4
    assert "history is wild, what era are u covering?" in selected
    assert "mm babe i'd hold u close" not in selected
    assert len({value.casefold() for value in selected}) == len(selected)


def test_structured_example_selection_uses_good_response_and_deduplicates():
    records = [
        {"id": 1, "good_response": "aww that made me smile"},
        {"id": 2, "good_response": "aww that made me smile"},
        {"id": 3, "good_response": "what happened after class?"},
        {"id": 4, "good_response": "which subject do u like most?"},
    ]

    selected = select_diverse_records(
        records,
        query="school class subject",
        recent_creator_messages=[],
        limit=3,
    )

    assert len(selected) == 3
    assert len({row["good_response"].casefold() for row in selected}) == 3


def test_prompt_guidance_names_recently_overused_patterns_without_messages():
    guidance = diversity_prompt_guidance(
        [
            "mm babe i'd hold u close, just us right here",
            "mmm i'd hold u tighter, just us right here",
            "mm i love that babe, what do u want next?",
        ]
    )

    assert "mm" in guidance.casefold()
    assert "do not reuse" in guidance.casefold()
    assert "just us" in guidance.casefold() or "closeness" in guidance.casefold()
