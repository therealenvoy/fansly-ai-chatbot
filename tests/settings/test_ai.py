from unittest.mock import MagicMock

import httpx
import pytest

from src.settings.ai import (
    AISettingsError,
    DEFAULT_DEEPSEEK_MODEL,
    DeepSeekSettingsService,
    EncryptedCredentialStore,
)
from src.settings.store import SettingsStore


@pytest.fixture
def store(tmp_path):
    value = SettingsStore(
        f"sqlite:///{tmp_path / 'ai-settings.db'}",
        creator_id="creator-a",
    )
    value.create_table()
    return value


def _service(store, *, encryption_key="e" * 32, environment_key=""):
    responder = MagicMock()
    extractor = MagicMock()
    service = DeepSeekSettingsService(
        settings_store=store,
        credential_store=EncryptedCredentialStore(
            store,
            encryption_key,
        ),
        environment_api_key=environment_key,
        chat_responder=responder,
        fact_extractor=extractor,
    )
    return service, responder, extractor


def _successful_models_response():
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [
            {"id": "deepseek-v4-flash"},
            {"id": "deepseek-v4-pro"},
        ]
    }
    return response


def test_default_model_is_v4_flash(store):
    service, _, _ = _service(store)

    assert service.model == DEFAULT_DEEPSEEK_MODEL
    assert service.status()["configured"] is False


def test_save_encrypts_key_and_applies_clients(store, monkeypatch):
    get = MagicMock(return_value=_successful_models_response())
    monkeypatch.setattr(httpx, "get", get)
    service, responder, extractor = _service(store)
    api_key = "deepseek-secret-value-with-enough-length"

    result = service.save(
        api_key=api_key,
        model="deepseek-v4-flash",
    )

    stored_secret = store.get("secret.deepseek_api_key.v1")
    assert stored_secret
    assert api_key not in stored_secret
    assert "api_key" not in result
    assert result["configured"] is True
    assert result["source"] == "encrypted_crm"
    responder.configure.assert_called_once_with(
        api_key=api_key,
        model="deepseek-v4-flash",
    )
    extractor.configure.assert_called_once_with(
        api_key=api_key,
        model="deepseek-v4-flash",
    )
    assert get.call_args.kwargs["headers"]["Authorization"].endswith(api_key)


def test_saved_key_survives_service_recreation(store, monkeypatch):
    monkeypatch.setattr(
        httpx,
        "get",
        MagicMock(return_value=_successful_models_response()),
    )
    first, _, _ = _service(store)
    api_key = "deepseek-secret-value-with-enough-length"
    first.save(api_key=api_key, model="deepseek-v4-flash")

    second, _, _ = _service(store)

    assert second.active_api_key() == (api_key, "encrypted_crm")


def test_saved_key_does_not_cross_creator_scope(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'creator-secrets.db'}"
    first_store = SettingsStore(db_url, creator_id="creator-a")
    second_store = SettingsStore(db_url, creator_id="creator-b")
    first_store.create_table()
    monkeypatch.setattr(
        httpx,
        "get",
        MagicMock(return_value=_successful_models_response()),
    )
    first, _, _ = _service(first_store)
    first.save(
        api_key="deepseek-secret-value-with-enough-length",
        model="deepseek-v4-flash",
    )

    second, _, _ = _service(second_store)

    assert second.active_api_key() == ("", "not_configured")


def test_saving_key_requires_server_encryption_key(store):
    service, _, _ = _service(store, encryption_key="")

    with pytest.raises(AISettingsError, match="CREDENTIAL_ENCRYPTION_KEY"):
        service.save(
            api_key="deepseek-secret-value-with-enough-length",
            model="deepseek-v4-flash",
        )


def test_model_can_change_using_environment_key(store, monkeypatch):
    monkeypatch.setattr(
        httpx,
        "get",
        MagicMock(return_value=_successful_models_response()),
    )
    service, responder, _ = _service(
        store,
        encryption_key="",
        environment_key="deepseek-environment-key-long-enough",
    )

    result = service.save(api_key=None, model="deepseek-v4-pro")

    assert result["model"] == "deepseek-v4-pro"
    assert result["source"] == "environment"
    responder.configure.assert_called_once_with(
        api_key="deepseek-environment-key-long-enough",
        model="deepseek-v4-pro",
    )


def test_probe_rejects_model_not_exposed_by_account(store, monkeypatch):
    response = _successful_models_response()
    response.json.return_value = {"data": [{"id": "deepseek-v4-pro"}]}
    monkeypatch.setattr(httpx, "get", MagicMock(return_value=response))
    service, _, _ = _service(store)

    with pytest.raises(AISettingsError, match="does not expose"):
        service.save(
            api_key="deepseek-secret-value-with-enough-length",
            model="deepseek-v4-flash",
        )



def test_save_applies_runtime_key_and_model_to_strategic_analyzer(
    store,
    monkeypatch,
):
    monkeypatch.setattr(
        httpx,
        "get",
        MagicMock(return_value=_successful_models_response()),
    )
    service, _, _ = _service(store)
    analyzer = MagicMock()
    service.strategic_analyzer = analyzer

    service.save(
        api_key="deepseek-secret-value-with-enough-length",
        model="deepseek-v4-pro",
    )

    analyzer.configure.assert_called_once_with(
        api_key="deepseek-secret-value-with-enough-length",
        model="deepseek-v4-pro",
    )
