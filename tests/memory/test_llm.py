"""Tests for LLMFactExtractor — DeepSeek-based fan fact extraction."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
from src.memory.llm import LLMFactExtractor


def test_disabled_without_api_key():
    ext = LLMFactExtractor(api_key=None)
    assert not ext.enabled
    assert ext.extract(["hello"]) == {}


def test_disabled_with_empty_key():
    ext = LLMFactExtractor(api_key="")
    assert not ext.enabled
    assert ext.extract(["hello"]) == {}


def test_empty_messages_returns_empty():
    ext = LLMFactExtractor(api_key="sk-test")
    assert ext.extract([]) == {}
    assert ext.extract([""]) == {}
    assert ext.extract(["   "]) == {}


def _mock_response(monkeypatch, content: str):
    """Mock httpx.post to return a fake DeepSeek response."""
    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp())


def test_extracts_valid_json(monkeypatch):
    payload = {
        "display_name": "Jake",
        "occupation": "engineer",
        "preferences": ["hiking", "blondes"],
        "emotional_triggers": ["compliments"],
        "hard_limits": ["no meetups"],
        "facts": ["has a dog named Rex", "lives in Austin"],
    }
    _mock_response(monkeypatch, json.dumps(payload))
    ext = LLMFactExtractor(api_key="sk-test")
    result = ext.extract(["I'm Jake, I'm an engineer in Austin with my dog Rex"])
    assert result["display_name"] == "Jake"
    assert result["occupation"] == "engineer"
    assert "hiking" in result["preferences"]
    assert "no meetups" in result["hard_limits"]
    assert len(result["facts"]) == 2


def test_fact_extraction_uses_v4_flash_without_thinking(monkeypatch):
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": "{}"}}]
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)

    LLMFactExtractor(api_key="sk-test").extract(["hello"])

    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["thinking"] == {"type": "disabled"}


def test_strips_markdown_fences(monkeypatch):
    payload = {"preferences": ["gym"]}
    _mock_response(monkeypatch, f"```json\n{json.dumps(payload)}\n```")
    ext = LLMFactExtractor(api_key="sk-test")
    result = ext.extract(["I love the gym"])
    assert result["preferences"] == ["gym"]


def test_invalid_json_returns_empty(monkeypatch):
    _mock_response(monkeypatch, "this is not json at all")
    ext = LLMFactExtractor(api_key="sk-test")
    assert ext.extract(["hello"]) == {}


def test_non_dict_json_returns_empty(monkeypatch):
    _mock_response(monkeypatch, '["just", "a", "list"]')
    ext = LLMFactExtractor(api_key="sk-test")
    assert ext.extract(["hello"]) == {}


def test_filters_wrong_types(monkeypatch):
    payload = {
        "display_name": 42,  # wrong type — should be dropped
        "preferences": "not a list",  # wrong type — dropped
        "facts": ["valid fact", "", None, 123],  # mixed — keeps truthy, stringified
    }
    _mock_response(monkeypatch, json.dumps(payload))
    ext = LLMFactExtractor(api_key="sk-test")
    result = ext.extract(["test"])
    assert "display_name" not in result
    assert "preferences" not in result
    assert "valid fact" in result["facts"]
    assert "" not in result["facts"]


def test_http_error_returns_empty(monkeypatch):
    import httpx
    def raise_error(*a, **k):
        raise httpx.HTTPError("boom")
    monkeypatch.setattr(httpx, "post", raise_error)
    ext = LLMFactExtractor(api_key="sk-test")
    assert ext.extract(["hello"]) == {}


# ─── NoteExtractor.merge with facts ──────────────────

from src.notes.extractor import NoteExtractor
from src.notes.models import FanNote


def _extractor():
    return NoteExtractor(llm_client=None)  # merge() doesn't use the client


def test_merge_appends_facts():
    note = FanNote(fan_id="f1", creator_id="c1", facts=["has a dog"])
    merged = _extractor().merge(note, {"facts": ["has a dog", "works nights"]})
    assert merged.facts == ["has a dog", "works nights"]


def test_merge_facts_no_duplicates():
    note = FanNote(fan_id="f1", creator_id="c1", facts=["a", "b"])
    merged = _extractor().merge(note, {"facts": ["b", "c"]})
    assert merged.facts == ["a", "b", "c"]


def test_merge_facts_into_empty():
    note = FanNote(fan_id="f1", creator_id="c1")
    merged = _extractor().merge(note, {"facts": ["first fact"]})
    assert merged.facts == ["first fact"]


# ─── Repository facts round-trip ─────────────────────

from src.notes.repository import FanNoteRepository


def test_repository_facts_roundtrip(tmp_path):
    repo = FanNoteRepository(f"sqlite:///{tmp_path}/notes.db")
    repo.create_table()
    note = FanNote(
        fan_id="f1", creator_id="c1",
        preferences=["gym"], facts=["dog named Rex", "lives in Austin"],
    )
    repo.save(note)
    loaded = repo.get("f1", "c1")
    assert loaded is not None
    assert loaded.facts == ["dog named Rex", "lives in Austin"]
    assert loaded.preferences == ["gym"]


def test_repository_facts_upsert(tmp_path):
    repo = FanNoteRepository(f"sqlite:///{tmp_path}/notes.db")
    repo.create_table()
    repo.save(FanNote(fan_id="f1", creator_id="c1", facts=["one"]))
    repo.save(FanNote(fan_id="f1", creator_id="c1", facts=["one", "two"]))
    loaded = repo.get("f1", "c1")
    assert loaded.facts == ["one", "two"]


def test_upsert_compiles_for_postgres():
    """Production runs on Postgres (NeonDB) — the upsert must compile for it."""
    from sqlalchemy.dialects import postgresql
    from src.notes.repository import FAN_NOTES_TABLE, _note_to_row
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    row = _note_to_row(FanNote(fan_id="f1", creator_id="c1", facts=["x"]))
    stmt = pg_insert(FAN_NOTES_TABLE).values(**row)
    stmt = stmt.on_conflict_do_update(
        index_elements=["fan_id", "creator_id"],
        set_={k: getattr(stmt.excluded, k) for k in ("display_name", "facts", "notes")},
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in sql
    assert "DO UPDATE" in sql
