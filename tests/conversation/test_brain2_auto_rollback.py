from src.conversation.authority import AutomaticRollbackEvaluator


def _attempt(**changes):
    item = {
        "authority": "advanced",
        "fallback_used": False,
        "fallback_reason": None,
        "route": "fast",
        "latency_ms": 1000,
        "gate_results": {},
    }
    item.update(changes)
    return item


def test_any_advanced_safety_violation_triggers_immediate_rollback():
    reason = AutomaticRollbackEvaluator().evaluate(
        [
            _attempt(
                fallback_used=True,
                fallback_reason="quality_gate_rejected",
                gate_results={"reason_codes": ["sales_or_ppv"]},
            )
        ]
    )
    assert reason == "advanced_safety_violation:sales_or_ppv"


def test_failure_json_timeout_and_latency_thresholds_use_last_100_attempts():
    evaluator = AutomaticRollbackEvaluator()
    healthy = [_attempt() for _ in range(100)]
    assert evaluator.evaluate(healthy) is None
    assert evaluator.evaluate(
        healthy[:-2]
        + [
            _attempt(fallback_used=True, fallback_reason="fast_json_invalid"),
            _attempt(fallback_used=True, fallback_reason="provider_server_error"),
        ]
    ) == "advanced_failure_rate"
    assert evaluator.evaluate(
        healthy[:-3]
        + [
            _attempt(fallback_used=True, fallback_reason="provider_timeout"),
            _attempt(fallback_used=True, fallback_reason="provider_timeout"),
            _attempt(fallback_used=True, fallback_reason="provider_timeout"),
        ]
    ) == "advanced_failure_rate"
    assert evaluator.evaluate(
        [_attempt(latency_ms=9000) for _ in range(6)]
        + [_attempt() for _ in range(94)]
    ) == "advanced_fast_latency_p95"


def test_insufficient_non_safety_sample_does_not_auto_rollback():
    attempts = [
        _attempt(fallback_used=True, fallback_reason="provider_timeout")
    ] + [_attempt() for _ in range(20)]
    assert AutomaticRollbackEvaluator().evaluate(attempts) is None
