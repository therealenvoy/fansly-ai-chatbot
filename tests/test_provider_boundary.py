"""Regression gate: production Fansly traffic has exactly one provider."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_source_contains_no_legacy_fansly_provider():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src").rglob("*.py")
    ).lower()

    assert "v1.apifansly.com" not in source
    assert "class apifanslyclient" not in source
    assert "apifansly_api_key" not in source


def test_onlyfansapi_is_the_single_fansly_http_origin():
    provider_source = (
        ROOT / "src" / "fansly_api_client.py"
    ).read_text(encoding="utf-8")
    factory_source = (
        ROOT / "src" / "client_factory.py"
    ).read_text(encoding="utf-8")

    assert 'BASE_URL = "https://app.onlyfansapi.com"' in provider_source
    assert "FanslyApiClientImpl" in factory_source


def test_bot_has_no_non_durable_send_path():
    bot_source = (ROOT / "src" / "bot.py").read_text(
        encoding="utf-8"
    )

    assert "def _process_chat(" not in bot_source
    assert "def _styled_send(" not in bot_source
    assert "Compatibility path for tests/dev" not in bot_source
