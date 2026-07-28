import json

from src.human_delivery.contracts import HumanDeliveryDecision
from src.human_delivery.documents import DocumentLinter, PromptCompiler
from src.human_delivery.settings import HumanDeliverySettings


def _decision(**overrides):
    value = {
        "understanding": {
            "language": "en",
            "fan_emotion": "playful",
            "relationship_stage": "warm",
            "unresolved_topic": None,
        },
        "strategy": {
            "primary_act": "playful_answer",
            "secondary_act": "callback",
            "should_ask_question": False,
            "safety_class": "conversation_only",
        },
        "delivery": {
            "casing_mode": "mostly_lowercase",
            "energy": "medium",
            "bubbles": [
                {"role": "reaction", "text": "stoppp 😭"},
                {"role": "answer", "text": "that actually made me smile"},
            ],
        },
        "memory_updates": [],
        "quality": {
            "facts_grounded": True,
            "sales_intent": False,
            "media_intent": False,
            "ppv_intent": False,
            "tip_intent": False,
            "confidence": 0.9,
        },
    }
    value.update(overrides)
    return value


def test_settings_fail_closed_and_deployment_ceiling_wins():
    disabled = HumanDeliverySettings.from_mapping(
        {
            "HUMAN_DELIVERY_MODE": "live",
            "HUMAN_DELIVERY_LIVE_PERCENT": "100",
            "HUMAN_DELIVERY_MAX_LIVE_PERCENT": "0",
            "HUMAN_DELIVERY_ALLOW_MULTI_BUBBLE_SEND": "true",
        }
    )
    assert disabled.live_authority is False
    assert disabled.live_percent == 0
    assert disabled.allow_multi_bubble_send is False

    capped = HumanDeliverySettings.from_mapping(
        {
            "HUMAN_DELIVERY_ENABLED": "true",
            "HUMAN_DELIVERY_MODE": "live",
            "HUMAN_DELIVERY_LIVE_PERCENT": "50",
            "HUMAN_DELIVERY_MAX_LIVE_PERCENT": "5",
            "HUMAN_DELIVERY_ALLOW_MULTI_BUBBLE_SEND": "true",
        }
    )
    assert capped.live_percent == 5
    assert capped.live_authority is True
    assert capped.allow_multi_bubble_send is True


def test_prompt_compiler_excludes_sales_and_reports_budget_omissions():
    compiler = PromptCompiler(budget=8_000)
    compiled = compiler.compile(
        runtime_rules="Conversation only. Never sell.",
        documents={
            "creator_persona": "# Facts\nLives in Toronto.",
            "brand_bible": "# World\nCats and rainy nights.",
            "conversation_guide": "# Style\nreply naturally",
            "sales_playbook": "# PPV\nsell this locked video",
        },
        newest_turn="fan: how was ur day?",
        conversation_only=True,
    )
    assert "sell this locked video" not in compiled.prompt
    assert "newest_fan_turn" in compiled.included
    assert {
        item["label"]: item["reason"]
        for item in compiled.excluded
    }["sales_playbook"] == "conversation_only"
    assert compiled.fingerprint == compiler.compile(
        runtime_rules="Conversation only. Never sell.",
        documents={
            "creator_persona": "# Facts\nLives in Toronto.",
            "brand_bible": "# World\nCats and rainy nights.",
            "conversation_guide": "# Style\nreply naturally",
            "sales_playbook": "# PPV\nsell this locked video",
        },
        newest_turn="fan: how was ur day?",
        conversation_only=True,
    ).fingerprint


def test_prompt_compiler_reserves_space_for_newest_turn_and_ranks_sections():
    compiler = PromptCompiler(budget=8_000)
    compiled = compiler.compile(
        runtime_rules="Conversation only.",
        documents={
            "creator_persona": (
                "# Skiing\n" + ("snow " * 900) +
                "\n\n# Cats\nThe creator has a verified cat named Luna."
            ),
            "brand_bible": "Never invent facts.",
            "conversation_guide": "Answer the newest turn first.",
        },
        creator_facts=["pet=Luna"],
        contact_policy="inbound reply permitted",
        newest_turn="how is Luna doing?",
    )
    assert "newest_fan_turn" in compiled.included
    assert compiled.character_count <= compiled.budget
    assert compiled.included.index(
        "creator_persona:2:Cats"
    ) < compiled.included.index(
        "creator_persona:1:Skiing"
    )


def test_linter_reports_sales_mixing_and_legacy_truncation():
    findings = DocumentLinter().lint(
        {
            "conversation_guide": (
                "Always ask a question in every reply.\n"
                "Offer a PPV discount and ask them to unlock it.\n"
                + ("x" * 20_100)
            ),
            "sales_playbook": "Pricing rules belong here.",
        }
    )
    codes = {finding.code for finding in findings}
    assert "sales_rules_mixed_into_conversation" in codes
    assert "legacy_runtime_truncation" in codes
    assert "forced_question_quota" in codes


def test_linter_reports_creator_fact_and_emotional_conflicts():
    findings = DocumentLinter().lint(
        {
            "creator_persona": (
                "Location: Paris\nAlways flirt in every conversation."
            ),
            "brand_bible": (
                "Location: Rome\nNever flirt with anyone."
            ),
            "conversation_guide": "Use at least 4 pet names.",
        }
    )
    codes = {finding.code for finding in findings}
    assert "conflicting_creator_fact" in codes
    assert "conflicting_emotional_positioning" in codes
    assert "excessive_phrase_quota" in codes
    assert "missing_factual_grounding" in codes


def test_structured_decision_accepts_meaningful_bubbles():
    decision = HumanDeliveryDecision.from_model_output(
        json.dumps(_decision()),
        conversation_only=True,
    )
    assert decision is not None
    assert len(decision.bubbles) == 2
    assert decision.combined_text == "stoppp 😭\nthat actually made me smile"
    assert len(decision.fingerprint) == 64


def test_structured_decision_rejects_sales_and_multiple_questions():
    sales = _decision()
    sales["quality"]["sales_intent"] = True
    assert HumanDeliveryDecision.from_model_output(
        json.dumps(sales)
    ) is None

    questions = _decision()
    questions["strategy"]["should_ask_question"] = True
    questions["delivery"]["bubbles"] = [
        {"role": "question", "text": "where are u?"},
        {"role": "question", "text": "what are u doing?"},
    ]
    assert HumanDeliveryDecision.from_model_output(
        json.dumps(questions)
    ) is None


def test_structured_decision_requires_memory_provenance():
    payload = _decision()
    payload["memory_updates"] = [
        {"type": "preference", "value": "likes rain"},
        {
            "type": "preference",
            "value": "likes cats",
            "source_message_id": "synthetic-message-1",
        },
    ]
    decision = HumanDeliveryDecision.from_model_output(json.dumps(payload))
    assert decision is not None
    assert decision.memory_updates == (
        {
            "type": "preference",
            "value": "likes cats",
            "source_message_id": "synthetic-message-1",
        },
    )


def test_structured_decision_rejects_private_reasoning_and_ungrounded_claims():
    private = _decision()
    private["quality"]["reasoning"] = "hidden private analysis"
    assert HumanDeliveryDecision.from_model_output(
        json.dumps(private)
    ) is None

    claim = _decision()
    claim["quality"]["creator_fact_claims"] = ["location=rome"]
    assert HumanDeliveryDecision.from_model_output(
        json.dumps(claim),
        verified_creator_facts={"location=paris"},
    ) is None
    assert HumanDeliveryDecision.from_model_output(
        json.dumps(claim),
        verified_creator_facts={"location=rome"},
    ) is not None
