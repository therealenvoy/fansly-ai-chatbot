import pytest

from src.service_role import ServiceRole


def test_all_role_runs_every_duty():
    role = ServiceRole.parse("all")
    assert role.serves_api
    assert role.runs_reply_workers
    assert role.runs_scheduler


@pytest.mark.parametrize(
    ("value", "api", "worker", "scheduler"),
    [
        ("api", True, False, False),
        ("worker", False, True, False),
        ("scheduler", False, False, True),
    ],
)
def test_dedicated_roles_are_mutually_exclusive(
    value,
    api,
    worker,
    scheduler,
):
    role = ServiceRole.parse(value)
    assert role.serves_api is api
    assert role.runs_reply_workers is worker
    assert role.runs_scheduler is scheduler


def test_invalid_role_fails_startup():
    with pytest.raises(ValueError, match="invalid SERVICE_ROLE"):
        ServiceRole.parse("everything")
