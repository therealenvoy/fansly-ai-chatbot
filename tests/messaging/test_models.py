import pytest

from src.messaging.models import OutboundKind, OutboundMessage


def test_builds_typed_text_media_and_ppv_messages():
    text = OutboundMessage.text("hello")
    media = OutboundMessage.media(
        "look",
        ("fansly_media_1",),
    )
    ppv = OutboundMessage.ppv(
        content="unlock",
        media_ids=("fansly_media_2",),
        price_millis=10_000,
        sequence_id=1,
        sequence_step_id=2,
    )

    assert text.kind == OutboundKind.TEXT
    assert media.kind == OutboundKind.MEDIA
    assert ppv.kind == OutboundKind.PPV
    assert ppv.price_millis == 10_000
    assert ppv.with_content("updated").media_ids == ppv.media_ids


@pytest.mark.parametrize(
    "factory",
    [
        lambda: OutboundMessage.text("  "),
        lambda: OutboundMessage.media("look", ()),
        lambda: OutboundMessage(
            kind=OutboundKind.MEDIA,
            content="look",
            media_ids=("fansly_media_1",),
            price_millis=1000,
        ),
        lambda: OutboundMessage.ppv(
            content="unlock",
            media_ids=(),
            price_millis=1000,
            sequence_id=1,
            sequence_step_id=1,
        ),
        lambda: OutboundMessage.ppv(
            content="unlock",
            media_ids=("fansly_media_1",),
            price_millis=0,
            sequence_id=1,
            sequence_step_id=1,
        ),
        lambda: OutboundMessage.ppv(
            content="unlock",
            media_ids=("fansly_media_1", "fansly_media_2"),
            price_millis=1000,
            sequence_id=1,
            sequence_step_id=1,
        ),
        lambda: OutboundMessage.ppv(
            content="unlock",
            media_ids=("fansly_media_1",),
            price_millis=10.5,
            sequence_id=1,
            sequence_step_id=1,
        ),
        lambda: OutboundMessage.ppv(
            content="unlock",
            media_ids=("fansly_media_1",),
            price_millis=1000,
            sequence_id=0,
            sequence_step_id=1,
        ),
    ],
)
def test_rejects_invalid_outbound_invariants(factory):
    with pytest.raises(ValueError):
        factory()
