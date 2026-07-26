from src.operations import RuntimeMonitor


def test_runtime_monitor_records_success_idle_and_failure():
    monitor = RuntimeMonitor()
    monitor.poll_started()
    monitor.poll_succeeded(had_activity=False)
    idle = monitor.snapshot()

    assert idle["last_poll_started_at"] is not None
    assert idle["last_poll_succeeded_at"] is not None
    assert idle["consecutive_idle_cycles"] == 1
    assert idle["consecutive_failures"] == 0

    monitor.poll_started()
    monitor.poll_failed(RuntimeError("provider exploded"))
    failed = monitor.snapshot()

    assert failed["last_error"] == "RuntimeError"
    assert failed["last_error_at"] is not None
    assert failed["consecutive_failures"] == 1
    assert failed["consecutive_idle_cycles"] == 0


def test_runtime_monitor_does_not_expose_error_text():
    monitor = RuntimeMonitor()
    monitor.poll_failed(RuntimeError("secret-token"))

    assert monitor.snapshot()["last_error"] == "RuntimeError"
