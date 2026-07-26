"""Typed outbound messages before durable provider delivery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class OutboundKind(str, Enum):
    TEXT = "text"
    MEDIA = "media"
    PPV = "ppv"


@dataclass(frozen=True)
class OutboundMessage:
    """A validated delivery intent with prices stored in millidollars."""

    kind: OutboundKind
    content: str
    media_ids: tuple[str, ...] = ()
    price_millis: int | None = None
    sequence_id: int | None = None
    sequence_step_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("outbound content must be text")
        if self.kind == OutboundKind.TEXT:
            if not self.content.strip():
                raise ValueError("text messages require non-empty content")
            if self.media_ids or self.price_millis is not None:
                raise ValueError("text messages cannot contain media or price")
        elif self.kind == OutboundKind.MEDIA:
            if not self.media_ids:
                raise ValueError("media messages require at least one media ID")
            if self.price_millis is not None:
                raise ValueError("free media messages cannot contain a price")
        elif self.kind == OutboundKind.PPV:
            if len(self.media_ids) != 1:
                raise ValueError("PPV messages require exactly one media ID")
            if (
                isinstance(self.price_millis, bool)
                or not isinstance(self.price_millis, int)
                or self.price_millis <= 0
            ):
                raise ValueError(
                    "PPV messages require a positive integer millidollar price"
                )
            if (
                isinstance(self.sequence_id, bool)
                or not isinstance(self.sequence_id, int)
                or self.sequence_id <= 0
                or isinstance(self.sequence_step_id, bool)
                or not isinstance(self.sequence_step_id, int)
                or self.sequence_step_id <= 0
            ):
                raise ValueError("PPV messages require sequence provenance")
        else:
            raise ValueError(f"unsupported outbound kind: {self.kind}")
        if any(
            not isinstance(media_id, str) or not media_id.strip()
            for media_id in self.media_ids
        ):
            raise ValueError("media IDs must be non-empty strings")

    @classmethod
    def text(cls, content: str) -> "OutboundMessage":
        return cls(kind=OutboundKind.TEXT, content=content)

    @classmethod
    def media(
        cls,
        content: str,
        media_ids: tuple[str, ...],
    ) -> "OutboundMessage":
        return cls(
            kind=OutboundKind.MEDIA,
            content=content,
            media_ids=media_ids,
        )

    @classmethod
    def ppv(
        cls,
        *,
        content: str,
        media_ids: tuple[str, ...],
        price_millis: int,
        sequence_id: int,
        sequence_step_id: int,
    ) -> "OutboundMessage":
        return cls(
            kind=OutboundKind.PPV,
            content=content,
            media_ids=media_ids,
            price_millis=price_millis,
            sequence_id=sequence_id,
            sequence_step_id=sequence_step_id,
        )

    def with_content(self, content: str) -> "OutboundMessage":
        return replace(self, content=content)
