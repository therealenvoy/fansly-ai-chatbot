from src.messaging.policy import MessageContentPolicy


def test_policy_normalizes_approved_content():
    policy = MessageContentPolicy()

    decision = policy.validate_inbound("  hello\r\nthere  ")

    assert decision.approved is True
    assert decision.content == "hello\nthere"
    assert decision.reason is None


def test_policy_rejects_empty_oversized_and_control_content():
    policy = MessageContentPolicy(
        max_inbound_chars=5,
        max_outbound_chars=4,
    )

    assert policy.validate_inbound(" \r\n ").approved is False
    assert policy.validate_inbound("123456").reason == (
        "inbound content exceeds 5 characters"
    )
    assert policy.validate_outbound("12345").reason == (
        "outbound content exceeds 4 characters"
    )
    assert policy.validate_outbound("a\x00b").reason == (
        "outbound content contains control characters"
    )


def test_policy_rejects_non_text_input():
    decision = MessageContentPolicy().validate_inbound(None)

    assert decision.approved is False
    assert decision.content == ""
    assert decision.reason == "inbound content must be text"
