from datetime import datetime, timezone

from sqlalchemy import create_engine, event, insert

from src.human_delivery.guide import DEFAULT_CONVERSATION_GUIDE
from src.human_delivery.service import HumanDeliveryService
from src.human_delivery.settings import HumanDeliverySettings
from src.persistence.schema import CREATORS, metadata


def _service():
    engine = create_engine("sqlite:///:memory:", future=True)
    metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            insert(CREATORS).values(
                id="creator-a",
                created_at=now,
                updated_at=now,
            )
        )
    service = HumanDeliveryService(
        engine,
        creator_id="creator-a",
        settings=HumanDeliverySettings(),
    )
    service.bootstrap(
        creator_persona="tone: playful",
        brand_bible="# Brand\nLikes rain.",
        conversation_guide="# Existing\nKeep replies warm.",
        suggested_guide=DEFAULT_CONVERSATION_GUIDE,
    )
    return service


def test_service_status_is_fail_closed_and_content_free():
    status = _service().status()
    assert status["settings"]["mode"] == "off"
    assert status["settings"]["live_authority"] is False
    assert status["safety"] == {
        "live_pipeline_changed": False,
        "preview_can_send": False,
        "repository_can_write_outbox": False,
        "sales_playbook_in_conversation_prompt": False,
        "deployment_ceiling_enforced": True,
    }
    assert "content" not in str(status)


def test_service_status_uses_one_database_round_trip():
    service = _service()
    statements = []

    def record_statement(*_args):
        statements.append(1)

    event.listen(
        service.engine,
        "before_cursor_execute",
        record_statement,
    )
    try:
        status = service.status()
    finally:
        event.remove(
            service.engine,
            "before_cursor_execute",
            record_statement,
        )

    assert len(statements) == 1
    assert status["documents"]["revision_count"] == 5
    assert status["shadow_evidence"]["plans_by_status"] == {}
    assert status["shadow_evidence"]["bubble_distribution"] == {
        "1": 0,
        "2": 0,
        "3": 0,
    }


def test_save_and_activate_revision_never_claims_runtime_authority():
    service = _service()
    draft = service.create_revision(
        {
            "document_type": "conversation_guide",
            "content": "# Better\nUse one bubble by default.",
        }
    )
    assert draft["status"] == "draft"
    active = service.activate(draft["id"])
    assert active["status"] == "active"
    assert service.settings.live_authority is False


def test_sales_playbook_cannot_be_activated_in_conversation_mode():
    service = _service()
    sales = next(
        document
        for document in service.list_documents()
        if document["document_type"] == "sales_playbook"
    )
    try:
        service.activate(sales["id"])
    except ValueError as error:
        assert "cannot be active" in str(error)
    else:
        raise AssertionError("sales playbook activation should fail")


def test_synthetic_preview_has_zero_external_calls_and_outbox_writes():
    service = _service()
    preview = service.preview(
        {
            "newest_turn": "invented: i finally finished my project",
            "history": "invented: the project took all week",
            "candidate_response": "stoppp thats huge || u must feel so relieved",
            "fan_style_samples": ["lol yeah", "i did ittt"],
            "recent_creator_messages": ["that sounds like a long week"],
        }
    )
    assert preview["mode"] == "synthetic_no_send"
    assert len(preview["bubbles"]) == 2
    assert preview["external_calls"] == 0
    assert preview["outbox_writes"] == 0
    assert "sales_playbook" not in preview["compilation"]["included"]
