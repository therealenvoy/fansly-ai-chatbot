import pytest
from sqlalchemy import create_engine, select

from src.persistence.schema import (
    CREATORS,
    PROVIDER_CREDIT_BUDGETS,
    PROVIDER_CREDIT_EVENTS,
    metadata,
)
from src.provider_credit import (
    ProviderBudgetExceeded,
    ProviderCircuitOpen,
    ProviderCreditGovernor,
    ProviderCreditSettings,
    provider_worker,
)


def _governor(**settings):
    engine = create_engine("sqlite:///:memory:", future=True)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            CREATORS.insert().values(id="creator-a")
        )
    return engine, ProviderCreditGovernor(
        engine,
        creator_id="creator-a",
        settings=ProviderCreditSettings(
            monthly_limit=settings.get("monthly_limit", 20),
            daily_read_limit=settings.get("daily_read_limit", 5),
            monthly_send_reserve=settings.get("monthly_send_reserve", 10),
            monthly_emergency_reserve=settings.get("monthly_emergency_reserve", 2),
        ),
    )


def test_reserves_then_records_actual_provider_usage_and_worker():
    engine, governor = _governor()

    with provider_worker("crm-backfill"):
        reservation = governor.reserve(
            "fansly.messages.list",
            request_class="read",
        )
    governor.finalize(
        reservation,
        method="GET",
        result="success",
        status_code=200,
        used_credits=1,
        balance=99,
    )

    with engine.connect() as connection:
        event = connection.execute(
            select(PROVIDER_CREDIT_EVENTS)
        ).mappings().one()
        budgets = connection.execute(
            select(PROVIDER_CREDIT_BUDGETS)
        ).mappings().all()
    assert event["operation"] == "fansly.messages.list"
    assert event["worker"] == "crm-backfill"
    assert event["balance"] == 99
    assert all(row["reserved_credits"] == 0 for row in budgets)
    assert all(row["used_credits"] == 1 for row in budgets)


def test_daily_read_budget_blocks_before_network_call():
    _, governor = _governor(daily_read_limit=1)
    first = governor.reserve("fansly.chats.list", request_class="read")
    governor.finalize(
        first,
        method="GET",
        result="success",
        status_code=200,
        used_credits=1,
    )

    with pytest.raises(ProviderBudgetExceeded):
        governor.reserve("fansly.chats.list", request_class="read")


def test_open_circuit_blocks_paid_call_until_explicit_reset():
    _, governor = _governor()
    governor.open_circuit("payment_required")

    with pytest.raises(ProviderCircuitOpen):
        governor.reserve("fansly.chats.list", request_class="read")

    assert governor.is_circuit_open() is True
    governor.reset_circuit()
    assert governor.is_circuit_open() is False


def test_zero_credit_control_call_can_run_while_circuit_is_open():
    _, governor = _governor()
    governor.open_circuit("payment_required")

    reservation = governor.reserve(
        "accounts.verify",
        request_class="control",
        credits=0,
        allow_when_open=True,
    )

    assert reservation.credits == 0
