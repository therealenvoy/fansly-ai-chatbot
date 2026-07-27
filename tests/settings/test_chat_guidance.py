from src.settings.chat_guidance import (
    BRAND_BIBLE_SETTING,
    CHAT_INSTRUCTIONS_SETTING,
    MAX_CHAT_INSTRUCTIONS_CHARS,
    ChatGuidanceError,
    ChatGuidanceService,
)
from src.settings.store import SettingsStore


def _store(tmp_path, creator_id="creator-a"):
    store = SettingsStore(
        f"sqlite:///{tmp_path / 'chat-guidance.db'}",
        creator_id=creator_id,
    )
    store.create_table()
    return store


def test_guidance_is_creator_scoped_and_persisted(tmp_path):
    first = _store(tmp_path, "creator-a")
    second = SettingsStore(
        engine=first.engine,
        creator_id="creator-b",
    )

    service = ChatGuidanceService(first)
    service.save_chat_instructions("Ask one natural question.")
    service.save_brand_bible("Sunny is playful and warm.")

    reloaded = ChatGuidanceService(first)
    other_creator = ChatGuidanceService(second)

    assert reloaded.snapshot().chat_instructions == (
        "Ask one natural question."
    )
    assert reloaded.snapshot().brand_bible == (
        "Sunny is playful and warm."
    )
    assert other_creator.snapshot().chat_instructions == ""
    assert other_creator.snapshot().brand_bible == ""
    assert first.get_scoped(CHAT_INSTRUCTIONS_SETTING) is not None
    assert first.get_scoped(BRAND_BIBLE_SETTING) is not None


def test_legacy_brand_bible_is_migrated_once(tmp_path):
    path = tmp_path / "brand_bible.md"
    path.write_text("Legacy creator identity", encoding="utf-8")
    store = _store(tmp_path)

    service = ChatGuidanceService(
        store,
        legacy_brand_bible_path=path,
    )

    assert service.snapshot().brand_bible == "Legacy creator identity"
    assert store.get_scoped(BRAND_BIBLE_SETTING) == (
        "Legacy creator identity"
    )

    path.write_text("Changed legacy file", encoding="utf-8")
    reloaded = ChatGuidanceService(
        store,
        legacy_brand_bible_path=path,
    )
    assert reloaded.snapshot().brand_bible == "Legacy creator identity"


def test_chat_instructions_reject_oversized_documents(tmp_path):
    service = ChatGuidanceService(_store(tmp_path))

    at_limit = "x" * MAX_CHAT_INSTRUCTIONS_CHARS
    assert (
        service.save_chat_instructions(at_limit).chat_instructions
        == at_limit
    )

    try:
        service.save_chat_instructions(
            "x" * (MAX_CHAT_INSTRUCTIONS_CHARS + 1)
        )
    except ChatGuidanceError as error:
        assert "characters or fewer" in str(error)
    else:
        raise AssertionError("oversized chatting instructions were saved")
