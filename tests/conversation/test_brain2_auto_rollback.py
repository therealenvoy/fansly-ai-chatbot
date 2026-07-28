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


def test_operational_safety_failures_rollback_without_a_sample_window():
    evaluator = AutomaticRollbackEvaluator()
    assert evaluator.evaluate(
        [],
        operational={"duplicate_outbox_writes": 1},
    ) == "advanced_duplicate_outbox_write"
    assert evaluator.evaluate(
        [],
        operational={"persistence_failures": 1},
    ) == "advanced_persistence_failure"
    assert evaluator.evaluate(
        [],
        operational={"kill_switch_requested": True},
    ) == "operator_kill_switch"


def test_outcome_regressions_compare_advanced_to_control_after_50_each():
    evaluator = AutomaticRollbackEvaluator()
    control = {
        "attempts": 50,
        "meaningful_replies": 30,
        "continuations": 20,
        "negative_signals": 1,
    }
    assert evaluator.evaluate(
        [],
        outcomes={
            "control": control,
            "advanced": {
                "attempts": 50,
                "meaningful_replies": 30,
                "continuations": 20,
                "negative_signals": 3,
            },
        },
    ) == "advanced_negative_signal_regression"
    assert evaluator.evaluate(
        [],
        outcomes={
            "control": control,
            "advanced": {
                "attempts": 50,
                "meaningful_replies": 28,
                "continuations": 20,
                "negative_signals": 1,
            },
        },
    ) == "advanced_meaningful_reply_regression"
    assert evaluator.evaluate(
        [],
        outcomes={
            "control": control,
            "advanced": {
                "attempts": 50,
                "meaningful_replies": 30,
                "continuations": 18,
                "negative_signals": 1,
            },
        },
    ) == "advanced_continuation_regression"


def test_outcome_regression_waits_for_sufficient_control_evidence():
    reason = AutomaticRollbackEvaluator().evaluate(
        [],
        outcomes={
            "control": {
                "attempts": 49,
                "meaningful_replies": 40,
                "continuations": 30,
                "negative_signals": 0,
            },
            "advanced": {
                "attempts": 50,
                "meaningful_replies": 0,
                "continuations": 0,
                "negative_signals": 50,
            },
        },
    )
    assert reason is None
