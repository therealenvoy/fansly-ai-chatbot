from datetime import timedelta

import httpx
from sqlalchemy import create_engine, select

from src.apifansly_client import ApifanslyAccountConnector
from src.creators.connections import (
    CreatorConnectionRepository,
    CreatorConnectionService,
    PendingConnectionStore,
)
from src.persistence.schema import (
    CREATOR_CONNECTIONS,
    CREATOR_SETTINGS,
    CREATORS,
    metadata,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(
        engine,
        tables=[CREATORS, CREATOR_CONNECTIONS, CREATOR_SETTINGS],
    )
    return engine


def test_repository_keeps_provider_ids_private_and_new_model_disabled():
    engine = _engine()
    repository = CreatorConnectionRepository(engine)
    repository.upsert(
        creator_id="second_model",
        provider_account_id="provider-secret-id",
        country_code="US",
        profile={
            "native_account_id": "native-secret-id",
            "display_name": "Second Model",
            "username": "second",
            "avatar_url": "https://example.test/avatar.jpg",
        },
    )

    public = repository.list_public()

    assert len(public) == 1
    assert public[0]["creator_id"] == "second_model"
    assert "provider_account_id" not in public[0]
    assert "native_account_id" not in public[0]
    with engine.connect() as connection:
        enabled = connection.execute(
            select(CREATOR_SETTINGS.c.value).where(
                CREATOR_SETTINGS.c.creator_id == "second_model",
                CREATOR_SETTINGS.c.key == "bot_enabled",
            )
        ).scalar_one()
    assert enabled == "false"


def test_pending_connection_is_bounded_and_process_local():
    store = PendingConnectionStore(ttl=timedelta(minutes=1))
    nonce = store.put(
        username="login",
        password="password-123",
        label="Second Model",
        country_code="US",
        two_factor_token="provider-token",
    )

    pending = store.get(nonce)

    assert pending.label == "Second Model"
    store.discard(nonce)
    try:
        store.get(nonce)
    except ValueError as error:
        assert "expired" in str(error)
    else:
        raise AssertionError("2FA handoff must be one-time")


def test_connector_uses_documented_payload_without_retries():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "requires_2fa": True,
                    "twofa_token": "temporary",
                    "masked_email": "m***@example.test",
                }
            },
        )

    connector = ApifanslyAccountConnector(api_key="api-key")
    connector.client.close()
    connector.client = httpx.Client(
        base_url="https://v1.apifansly.com/api/fansly",
        headers={"x-api-key": "api-key"},
        transport=httpx.MockTransport(handler),
    )

    response = connector.connect(
        username="creator@example.test",
        password="not-persisted",
        name="Second Model",
        country_code="US",
    )

    assert response["requires_2fa"] is True
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/api/fansly/connect")
    assert requests[0].read()
    assert requests[0].headers["x-api-key"] == "api-key"


def test_connector_lists_connected_accounts_without_exposing_email():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "statusCode": 200,
                "data": {
                    "success": True,
                    "count": 2,
                    "accounts": [
                        {
                            "accountId": "fansly-provider-one",
                            "email": "private-one@example.test",
                            "name": "First Creator",
                            "country": "US",
                        },
                        {
                            "accountId": "fansly-provider-two",
                            "email": "private-two@example.test",
                            "name": "Second Creator",
                            "country": "GB",
                        },
                    ],
                },
            },
        )

    connector = ApifanslyAccountConnector(api_key="api-key")
    connector.client.close()
    connector.client = httpx.Client(
        base_url="https://v1.apifansly.com/api/fansly",
        headers={"x-api-key": "api-key"},
        transport=httpx.MockTransport(handler),
    )

    accounts = connector.list_accounts()

    assert accounts == [
        {
            "account_id": "fansly-provider-one",
            "name": "First Creator",
            "country_code": "US",
        },
        {
            "account_id": "fansly-provider-two",
            "name": "Second Creator",
            "country_code": "GB",
        },
    ]
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path.endswith("/api/fansly/accounts")
    assert "private-one@example.test" not in repr(accounts)


def test_service_syncs_existing_provider_accounts_without_reconnecting():
    engine = _engine()
    repository = CreatorConnectionRepository(engine)
    repository.ensure_legacy(
        "sunny_charm",
        "fansly-provider-one",
        display_name="Sunny Charm",
    )
    service = CreatorConnectionService(repository, api_key="api-key")
    service.connector.list_accounts = lambda: [
        {
            "account_id": "fansly-provider-one",
            "name": "Sunny Charm",
            "country_code": "US",
        },
        {
            "account_id": "fansly-provider-two",
            "name": "Second Creator",
            "country_code": "GB",
        },
        {
            "account_id": "fansly-provider-three",
            "name": "Third Creator",
            "country_code": "DE",
        },
    ]
    service.connector.connect = lambda **_: (_ for _ in ()).throw(
        AssertionError("sync must not reconnect an existing account")
    )

    result = service.sync_connected_accounts()

    assert result["provider_count"] == 3
    assert result["imported"] == 2
    assert len(result["models"]) == 3
    assert {
        model["display_name"] for model in result["models"]
    } == {"Sunny Charm", "Second Creator", "Third Creator"}
    assert all("provider_account_id" not in model for model in result["models"])
    with engine.connect() as connection:
        disabled = connection.execute(
            select(CREATOR_SETTINGS.c.value).where(
                CREATOR_SETTINGS.c.creator_id.in_(
                    ["second_creator", "third_creator"]
                ),
                CREATOR_SETTINGS.c.key == "bot_enabled",
            )
        ).scalars().all()
    assert disabled == ["false", "false"]


def test_service_sync_disambiguates_duplicate_provider_names():
    engine = _engine()
    service = CreatorConnectionService(
        CreatorConnectionRepository(engine),
        api_key="api-key",
    )
    service.connector.list_accounts = lambda: [
        {
            "account_id": "fansly-provider-one",
            "name": "Same Creator",
            "country_code": "US",
        },
        {
            "account_id": "fansly-provider-two",
            "name": "Same Creator",
            "country_code": "US",
        },
    ]

    first = service.sync_connected_accounts()
    second = service.sync_connected_accounts()

    first_ids = [model["creator_id"] for model in first["models"]]
    second_ids = [model["creator_id"] for model in second["models"]]
    assert len(set(first_ids)) == 2
    assert first_ids == second_ids
    assert second["imported"] == 0


def test_service_lists_legacy_model_without_provider_request():
    engine = _engine()
    repository = CreatorConnectionRepository(engine)
    repository.ensure_legacy(
        "sunny_charm",
        "existing-account",
        display_name="Sunny Charm",
    )

    service = CreatorConnectionService(repository, api_key="api-key")

    assert service.list_public()[0]["display_name"] == "Sunny Charm"
