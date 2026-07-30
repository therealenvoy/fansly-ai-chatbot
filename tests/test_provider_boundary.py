"""Regression gates for the automated-PPV provider boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_apifansly_is_the_paid_ppv_provider():
    provider_source = (
        ROOT / "src" / "apifansly_client.py"
    ).read_text(encoding="utf-8")
    factory_source = (
        ROOT / "src" / "client_factory.py"
    ).read_text(encoding="utf-8")

    assert (
        'BASE_URL = "https://v1.apifansly.com/api/fansly"'
        in provider_source
    )
    assert "supports_paid_messages=True" in provider_source
    assert "supports_vault_albums=True" in provider_source
    assert "ApifanslyClient" in factory_source


def test_apifansly_is_the_only_reachable_provider():
    factory_source = (
        ROOT / "src" / "client_factory.py"
    ).read_text(encoding="utf-8")

    assert not (ROOT / "src" / "fansly_api_client.py").exists()
    assert "FanslyApiClientImpl" not in factory_source
    assert 'env.get("FANSLY_API_KEY"' not in factory_source
    assert "Only 'apifansly' is supported" in factory_source


def test_bot_has_no_non_durable_send_path():
    bot_source = (ROOT / "src" / "bot.py").read_text(
        encoding="utf-8"
    )

    assert "def _process_chat(" not in bot_source
    assert "def _styled_send(" not in bot_source
    assert "Compatibility path for tests/dev" not in bot_source
