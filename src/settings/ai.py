"""Secure creator-scoped configuration for the conversation model."""

from __future__ import annotations

import base64
import hashlib
import re
import threading
from datetime import datetime, timezone

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .store import SettingsStore


DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
SUPPORTED_DEEPSEEK_MODELS = (
    "deepseek-v4-flash",
    "deepseek-v4-pro",
)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_MODEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SECRET_SETTING = "secret.deepseek_api_key.v1"
_MODEL_SETTING = "deepseek.model"


class AISettingsError(ValueError):
    """Safe operator-facing configuration error."""


class EncryptedCredentialStore:
    """Encrypt secrets before persisting them in creator settings."""

    def __init__(
        self,
        settings_store: SettingsStore,
        encryption_key: str | None,
    ):
        self.settings_store = settings_store
        raw_key = (encryption_key or "").strip()
        self._fernet = None
        self._configuration_error = None
        if raw_key:
            if len(raw_key) < 32:
                self._configuration_error = (
                    "CREDENTIAL_ENCRYPTION_KEY must contain at least "
                    "32 characters"
                )
            else:
                derived = base64.urlsafe_b64encode(
                    hashlib.sha256(raw_key.encode("utf-8")).digest()
                )
                self._fernet = Fernet(derived)

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise AISettingsError(
                self._configuration_error
                or "Secure credential storage is unavailable. Configure "
                "CREDENTIAL_ENCRYPTION_KEY on the server first."
            )
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def read(self) -> str | None:
        token = self.settings_store.get_scoped(_SECRET_SETTING)
        if not token:
            return None
        if self._fernet is None:
            raise AISettingsError(
                "The saved DeepSeek credential cannot be decrypted because "
                "CREDENTIAL_ENCRYPTION_KEY is not configured."
            )
        try:
            return self._fernet.decrypt(
                str(token).encode("ascii")
            ).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise AISettingsError(
                "The saved DeepSeek credential could not be decrypted."
            ) from exc


def normalize_deepseek_model(value: str | None) -> str:
    model = (value or DEFAULT_DEEPSEEK_MODEL).strip().lower()
    if not _MODEL_PATTERN.fullmatch(model):
        raise AISettingsError("Invalid DeepSeek model name")
    if model not in SUPPORTED_DEEPSEEK_MODELS:
        raise AISettingsError(
            "Unsupported DeepSeek model. Choose deepseek-v4-flash or "
            "deepseek-v4-pro."
        )
    return model


class DeepSeekSettingsService:
    """Validate, persist, and apply DeepSeek settings without exposing keys."""

    def __init__(
        self,
        *,
        settings_store: SettingsStore,
        credential_store: EncryptedCredentialStore,
        environment_api_key: str | None,
        environment_model: str | None = None,
        chat_responder=None,
        fact_extractor=None,
        timeout: float = 15.0,
    ):
        self.settings_store = settings_store
        self.credential_store = credential_store
        self.environment_api_key = (environment_api_key or "").strip()
        stored_model = settings_store.get_scoped(
            _MODEL_SETTING,
            environment_model or DEFAULT_DEEPSEEK_MODEL,
        )
        self.model = normalize_deepseek_model(stored_model)
        self.chat_responder = chat_responder
        self.fact_extractor = fact_extractor
        self.timeout = timeout
        self._lock = threading.RLock()
        self._last_checked_at: datetime | None = None
        self._last_test_ok: bool | None = None
        self._last_error: str | None = None

    def _stored_api_key(self) -> str | None:
        return self.credential_store.read()

    def active_api_key(self) -> tuple[str, str]:
        stored = self._stored_api_key()
        if stored:
            return stored, "encrypted_crm"
        if self.environment_api_key:
            return self.environment_api_key, "environment"
        return "", "not_configured"

    def apply_runtime(self) -> None:
        with self._lock:
            api_key, _ = self.active_api_key()
            for client in (self.chat_responder, self.fact_extractor):
                if client is None:
                    continue
                configure = getattr(client, "configure", None)
                if callable(configure):
                    configure(api_key=api_key, model=self.model)

    def status(self) -> dict:
        with self._lock:
            try:
                api_key, source = self.active_api_key()
                credential_error = None
            except AISettingsError as exc:
                api_key = ""
                source = "encrypted_crm_error"
                credential_error = str(exc)
            return {
                "provider": "DeepSeek",
                "configured": bool(api_key),
                "model": self.model,
                "source": source,
                "secure_storage_available": (
                    self.credential_store.available
                ),
                "supported_models": list(SUPPORTED_DEEPSEEK_MODELS),
                "last_test_ok": self._last_test_ok,
                "last_checked_at": (
                    self._last_checked_at.isoformat()
                    if self._last_checked_at
                    else None
                ),
                "error": credential_error or self._last_error,
            }

    def _validate_api_key(self, api_key: str) -> str:
        normalized = api_key.strip()
        if len(normalized) < 20 or len(normalized) > 512:
            raise AISettingsError("DeepSeek API key has an invalid length")
        if any(
            ord(character) < 33 or ord(character) > 126
            for character in normalized
        ):
            raise AISettingsError(
                "DeepSeek API key contains invalid characters"
            )
        return normalized

    def _probe(self, api_key: str, model: str) -> None:
        try:
            response = httpx.get(
                f"{DEEPSEEK_BASE_URL}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                raise AISettingsError(
                    "DeepSeek rejected the API key"
                ) from exc
            raise AISettingsError(
                f"DeepSeek connection test failed with HTTP {status}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AISettingsError(
                "DeepSeek connection test could not be completed"
            ) from exc

        if not isinstance(payload, dict) or not isinstance(
            payload.get("data"),
            list,
        ):
            raise AISettingsError(
                "DeepSeek returned an invalid model-list response"
            )
        model_ids = {
            str(item.get("id", "")).strip()
            for item in payload.get("data", [])
            if isinstance(item, dict)
        }
        if model not in model_ids:
            raise AISettingsError(
                f"DeepSeek account does not expose model '{model}'"
            )

    def test_connection(self) -> dict:
        with self._lock:
            try:
                api_key, _ = self.active_api_key()
                if not api_key:
                    raise AISettingsError(
                        "DeepSeek API key is not configured"
                    )
                self._probe(api_key, self.model)
            except AISettingsError as exc:
                self._last_checked_at = datetime.now(timezone.utc)
                self._last_test_ok = False
                self._last_error = str(exc)
                raise
            self._last_checked_at = datetime.now(timezone.utc)
            self._last_test_ok = True
            self._last_error = None
            return self.status()

    def save(self, *, api_key: str | None, model: str | None) -> dict:
        with self._lock:
            selected_model = normalize_deepseek_model(
                model or self.model
            )
            if api_key is not None:
                candidate_key = self._validate_api_key(api_key)
                encrypted_key = self.credential_store.encrypt(
                    candidate_key
                )
            else:
                candidate_key, _ = self.active_api_key()
                encrypted_key = None
                if not candidate_key:
                    raise AISettingsError(
                        "Enter a DeepSeek API key before saving"
                    )

            self._probe(candidate_key, selected_model)
            values = {_MODEL_SETTING: selected_model}
            if encrypted_key is not None:
                values[_SECRET_SETTING] = encrypted_key
            self.settings_store.set_many(values)
            self.model = selected_model
            self._last_checked_at = datetime.now(timezone.utc)
            self._last_test_ok = True
            self._last_error = None
            self.apply_runtime()
            return self.status()
