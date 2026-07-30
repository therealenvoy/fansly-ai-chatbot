from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine, insert, select

from src.bulk_posting.schema import BULK_POST_OCCURRENCES, BULK_POST_RULES
from src.bulk_posting.service import BulkPostingError, BulkPostingService
from src.fansly_client import PaymentRequiredError
from src.persistence.schema import CREATORS, metadata
from src.web.dashboard import DASHBOARD_HTML


class FakePostingClient:
    def __init__(self):
        self.posts = []

    def list_post_walls(self):
        return [{"id": "wall-1", "name": "Subscribers"}]

    def create_post(self, **payload):
        self.posts.append(payload)
        return {"id": f"post-{len(self.posts)}"}


def _service():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(CREATORS).values(
                id="creator-1",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    client = FakePostingClient()
    return BulkPostingService(
        engine,
        creator_id="creator-1",
        client=client,
    ), client


def _payload(**changes):
    payload = {
        "caption": "new set",
        "tags": ["FYP", "#kawaii", "fyp"],
        "wall_ids": ["wall-1"],
        "media": [
            {
                "name": "one.jpg",
                "media_type": "image",
                "media_id": "media-1",
                "account_media_id": "account-media-1",
            }
        ],
        "recurrence": "one_time",
        "carousel": False,
        "paid_preview": False,
        "scheduled_for": (
            datetime.now(timezone.utc) + timedelta(hours=2)
        ).isoformat(),
        "expires_at": "",
    }
    payload.update(changes)
    return payload


def test_schedule_submits_documented_post_and_updates_metrics():
    service, client = _service()
    payload = _payload()

    result = service.schedule(payload, actor="posting-va")
    status = service.snapshot()
    with service.engine.connect() as connection:
        created_by = connection.execute(
            select(BULK_POST_RULES.c.created_by)
        ).scalar_one()

    assert result["status"] == "scheduled"
    assert client.posts[0]["content"] == "new set\n\n#fyp #kawaii"
    assert client.posts[0]["wall_ids"] == ["wall-1"]
    assert client.posts[0]["media_ids"] == ["media-1"]
    assert client.posts[0]["scheduled_for"] == int(
        datetime.fromisoformat(payload["scheduled_for"]).timestamp() * 1000
    )
    assert status["metrics"]["scheduled_posts"] == 1
    assert status["metrics"]["delivery_rate"] == 100.0
    assert status["posts"][0]["status"] == "submitted"
    assert created_by == "posting-va"


def test_unchecked_carousel_creates_one_post_per_media():
    service, client = _service()
    payload = _payload(
        media=[
            {
                "media_id": "media-1",
                "account_media_id": "account-media-1",
            },
            {
                "media_id": "media-2",
                "account_media_id": "account-media-2",
            },
        ]
    )

    service.schedule(payload)

    assert [post["media_ids"] for post in client.posts] == [
        ["media-1"],
        ["media-2"],
    ]


def test_confirmed_provider_rejection_is_not_delivery_unknown():
    service, client = _service()
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://provider.invalid/posts"),
    )

    def reject_post(**_payload):
        raise httpx.HTTPStatusError(
            "provider rejected post",
            request=response.request,
            response=response,
        )

    client.create_post = reject_post

    with pytest.raises(BulkPostingError, match="rejected"):
        service.schedule(_payload())

    with service.engine.connect() as connection:
        occurrence = connection.execute(
            select(
                BULK_POST_OCCURRENCES.c.status,
                BULK_POST_OCCURRENCES.c.error_code,
            )
        ).one()

    assert occurrence.status == "failed"
    assert occurrence.error_code == "provider_http_400"


def test_paid_preview_fails_closed():
    service, _ = _service()

    try:
        service.schedule(_payload(paid_preview=True))
    except BulkPostingError as error:
        assert "not supported" in str(error)
    else:
        raise AssertionError("paid preview must fail closed")


def test_snapshot_degrades_cleanly_when_provider_requires_payment():
    service, client = _service()

    def payment_required():
        raise PaymentRequiredError("provider billing required")

    client.list_post_walls = payment_required

    status = service.snapshot()

    assert status["available"] is False
    assert status["walls"] == []
    assert "payment" in status["reason"].lower()


def test_bulk_posting_dashboard_contains_only_required_control_surface():
    assert 'data-tab="bulk-posting"' in DASHBOARD_HTML
    assert "Scheduled Posts" in DASHBOARD_HTML
    assert "Next Post" in DASHBOARD_HTML
    assert "Recurring Rules" in DASHBOARD_HTML
    assert "Delivery Rate" in DASHBOARD_HTML
    assert "Group multiple media as one carousel" in DASHBOARD_HTML
    assert "Use first image as paid-post preview" in DASHBOARD_HTML
