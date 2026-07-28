from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import create_engine, func, select

from src.fansly_api_client import FanslyApiClientImpl
from src.fansly_client import (
    PaymentRequiredError,
    ProviderDeliveryUnknownError,
)
from src.persistence.schema import (
    CREATORS,
    PROVIDER_CREDIT_EVENTS,
    metadata,
)
from src.provider_credit import (
    ProviderCircuitOpen,
    ProviderCreditGovernor,
    ProviderCreditSettings,
    provider_worker,
)


def _response(body, status=200, headers=None):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.json.return_value = body
    response.headers = headers or {}
    return response


def _client():
    engine = create_engine("sqlite:///:memory:", future=True)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(CREATORS.insert().values(id="creator-a"))
    governor = ProviderCreditGovernor(
        engine,
        creator_id="creator-a",
        settings=ProviderCreditSettings(
            monthly_limit=100,
            daily_read_limit=20,
            monthly_send_reserve=50,
            monthly_emergency_reserve=10,
        ),
    )
    client = FanslyApiClientImpl(
        api_key="secret-provider-key",
        credit_governor=governor,
    )
    client._account_id = "fansly_account_secret"
    client._creator_fansly_id = "creator_secret"
    return engine, governor, client


def test_402_costs_zero_opens_durable_circuit_and_never_leaks_response():
    engine, governor, client = _client()
    client.client.request = MagicMock(
        return_value=_response(
            {
                "error": "secret response body",
                "_meta": {"_credits": {"used": 99, "balance": 0}},
            },
            status=402,
        )
    )

    with provider_worker("provider-reconciliation"):
        with pytest.raises(PaymentRequiredError) as captured:
            client.list_chats_page()

    message = str(captured.value)
    assert "secret" not in message
    assert "fansly_account" not in message
    assert governor.is_circuit_open() is True
    with engine.connect() as connection:
        event = connection.execute(
            select(PROVIDER_CREDIT_EVENTS)
        ).mappings().one()
    assert event["used_credits"] == 0
    assert event["result"] == "payment_required"
    assert event["worker"] == "provider-reconciliation"

    with pytest.raises(ProviderCircuitOpen):
        client.list_chats_page()
    client.client.request.assert_called_once()


def test_idempotent_get_retries_once_and_reserves_each_attempt():
    engine, _, client = _client()
    client.client.request = MagicMock(
        side_effect=[
            _response({"error": "temporary"}, status=503),
            _response(
                {
                    "data": {
                        "data": [],
                        "aggregationData": {"accounts": []},
                        "hasMore": False,
                    },
                    "_meta": {"_credits": {"used": 1, "balance": 98}},
                }
            ),
        ]
    )

    chats, next_offset = client.list_chats_page()

    assert chats == []
    assert next_offset is None
    assert client.client.request.call_count == 2
    with engine.connect() as connection:
        event_count = connection.execute(
            select(func.count()).select_from(PROVIDER_CREDIT_EVENTS)
        ).scalar_one()
    assert event_count == 2


def test_non_idempotent_timeout_is_not_retried():
    _, _, client = _client()
    client.client.request = MagicMock(
        side_effect=httpx.ReadTimeout("delivery unknown")
    )

    with pytest.raises(ProviderDeliveryUnknownError):
        client.send_message("chat_secret", "hello")

    client.client.request.assert_called_once()
