"""Tests for the objection handling dispatcher."""

import pytest
from src.objections.dispatcher import ObjectionDispatcher


class FakeSession:
    """Minimal session stub for testing objection pause/resume flow."""

    def __init__(self) -> None:
        self._objection_mode: bool = False


@pytest.fixture
def dispatcher() -> ObjectionDispatcher:
    """Create a fresh ObjectionDispatcher instance."""
    return ObjectionDispatcher()


@pytest.fixture
def session() -> FakeSession:
    """Create a fresh FakeSession instance."""
    return FakeSession()


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

class TestClassifyObjection:
    """Tests for classify_objection() returning the correct objection type."""

    def test_classify_price_objection(self, dispatcher: ObjectionDispatcher) -> None:
        """Messages mentioning high cost → 'price'."""
        result = dispatcher.classify_objection("That's too expensive for me")
        assert result == "price"

    def test_classify_free_request(self, dispatcher: ObjectionDispatcher) -> None:
        """Messages asking for free content → 'free_request'."""
        result = dispatcher.classify_objection("Can you send me a free sample?")
        assert result == "free_request"

    def test_classify_hesitation(self, dispatcher: ObjectionDispatcher) -> None:
        """Messages showing indecision → 'hesitation'."""
        result = dispatcher.classify_objection("Hmm I need to think about it")
        assert result == "hesitation"

    def test_classify_already_bought(self, dispatcher: ObjectionDispatcher) -> None:
        """Messages claiming prior purchase → 'already_bought'."""
        result = dispatcher.classify_objection("I already bought this yesterday")
        assert result == "already_bought"

    def test_classify_unknown(self, dispatcher: ObjectionDispatcher) -> None:
        """Messages that don't match any objection → 'unknown'."""
        result = dispatcher.classify_objection("Hey, how are you doing?")
        assert result == "unknown"


# ---------------------------------------------------------------------------
# Handler script resolution
# ---------------------------------------------------------------------------

class TestGetHandler:
    """Tests for get_handler() returning the correct script template name."""

    def test_get_handler_returns_script_name(self, dispatcher: ObjectionDispatcher) -> None:
        """Each known objection type maps to a handler script name."""
        assert dispatcher.get_handler("price") == "handle_price_objection"
        assert dispatcher.get_handler("free_request") == "handle_free_request"
        assert dispatcher.get_handler("hesitation") == "handle_hesitation"
        assert dispatcher.get_handler("already_bought") == "handle_already_bought"
        assert dispatcher.get_handler("unknown") == "handle_unknown_objection"


# ---------------------------------------------------------------------------
# Pause / resume flow
# ---------------------------------------------------------------------------

class TestPauseResumeFlow:
    """Tests for objection mode pause/resume on a session."""

    def test_pause_resume_cycle(
        self, dispatcher: ObjectionDispatcher, session: FakeSession
    ) -> None:
        """pause sets objection mode, resume clears it, is_in_objection reflects state."""
        assert not dispatcher.is_in_objection(session)

        dispatcher.pause_main_flow(session)
        assert dispatcher.is_in_objection(session)

        dispatcher.resume_main_flow(session)
        assert not dispatcher.is_in_objection(session)
