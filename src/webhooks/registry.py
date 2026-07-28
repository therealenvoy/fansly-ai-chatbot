"""Versioned registry for the live OnlyFansAPI Fansly webhook contract.

The registry deliberately separates a desired profile from handler readiness.
Registration code must use :func:`eligible_event_names`, never the profile
constant directly, so a planned event cannot be subscribed by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping


CATALOG_VERSION = "fansly-2026-07-28"
PARSER_VERSION = "1"
CORE_V1_PROFILE = "core_v1"


class HandlerReadiness(StrEnum):
    READY = "ready"
    PLANNED = "planned"
    IGNORED = "ignored"


class RetentionClass(StrEnum):
    EPHEMERAL = "ephemeral"
    OPERATIONAL = "operational"
    SAFETY = "safety"
    FINANCIAL = "financial"


@dataclass(frozen=True)
class FanslyEventSpec:
    name: str
    description: str
    family: str
    handler_name: str
    parser_version: str
    readiness: HandlerReadiness
    subscription_eligible: bool
    persistence_targets: tuple[str, ...]
    enqueues_conversation_work: bool
    affects_sending_authority: bool
    intentionally_ignored: bool
    subject_id_paths: tuple[str, ...]
    provider_timestamp_paths: tuple[str, ...]
    retention: RetentionClass

    @property
    def handler_ready(self) -> bool:
        return (
            self.readiness is HandlerReadiness.READY
            and self.subscription_eligible
            and not self.intentionally_ignored
        )


@dataclass(frozen=True)
class CatalogDrift:
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    description_mismatches: tuple[str, ...]

    @property
    def has_drift(self) -> bool:
        return bool(
            self.missing
            or self.unexpected
            or self.description_mismatches
        )


def _spec(
    name: str,
    description: str,
    family: str,
    handler_name: str,
    *,
    readiness: HandlerReadiness = HandlerReadiness.PLANNED,
    eligible: bool = False,
    targets: tuple[str, ...] = ("provider_webhook_events",),
    enqueue: bool = False,
    affects_send: bool = False,
    ignored: bool = False,
    subject: tuple[str, ...] = ("payload.id", "data.id"),
    timestamps: tuple[str, ...] = (
        "payload.createdAt",
        "data.createdAt",
        "created_at",
    ),
    retention: RetentionClass = RetentionClass.OPERATIONAL,
) -> FanslyEventSpec:
    return FanslyEventSpec(
        name=name,
        description=description,
        family=family,
        handler_name=handler_name,
        parser_version=PARSER_VERSION,
        readiness=readiness,
        subscription_eligible=eligible,
        persistence_targets=targets,
        enqueues_conversation_work=enqueue,
        affects_sending_authority=affects_send,
        intentionally_ignored=ignored,
        subject_id_paths=subject,
        provider_timestamp_paths=timestamps,
        retention=retention,
    )


_SPECS = (
    _spec(
        "fansly.messages.received",
        "Fansly message received",
        "chat",
        "handle_message_received",
        readiness=HandlerReadiness.READY,
        eligible=True,
        targets=(
            "provider_webhook_events",
            "fans",
            "conversations",
            "inbound_messages",
            "inbound_work_items",
        ),
        enqueue=True,
        affects_send=True,
        subject=("payload.id", "payload.message.id", "data.id"),
    ),
    _spec(
        "fansly.messages.sent",
        "Fansly message sent",
        "chat",
        "handle_message_sent",
        targets=(
            "provider_webhook_events",
            "fan_messages",
            "outbox_messages",
            "contact_trigger_claims",
        ),
        affects_send=True,
        subject=("payload.id", "payload.message.id", "data.id"),
    ),
    _spec(
        "fansly.messages.deleted",
        "Fansly message deleted",
        "chat",
        "handle_message_deleted",
        targets=("provider_webhook_events", "fan_messages"),
        affects_send=True,
        subject=("payload.id", "payload.message.id", "data.id"),
    ),
    _spec(
        "fansly.users.typing",
        "Fansly user typing",
        "presence",
        "ignore_user_typing",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        retention=RetentionClass.EPHEMERAL,
        subject=("payload.userId", "data.userId"),
    ),
    _spec(
        "fansly.messages.read",
        "Fansly messages read",
        "chat",
        "handle_messages_read",
        targets=("provider_webhook_events", "fan_messages"),
        subject=("payload.messageId", "data.messageId", "payload.groupId"),
    ),
    _spec(
        "fansly.subscriptions.new",
        "Fansly new subscription",
        "lifecycle",
        "handle_subscription_new",
        targets=(
            "provider_webhook_events",
            "fans",
            "fan_subscriptions",
        ),
        subject=("payload.subscription.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.tips.received",
        "Fansly tip received",
        "revenue",
        "handle_tip_received",
        targets=(
            "provider_webhook_events",
            "provider_wallet_transactions",
            "fan_revenue_events",
        ),
        subject=("payload.transaction.id", "payload.id", "data.id"),
        retention=RetentionClass.FINANCIAL,
    ),
    _spec(
        "fansly.transactions.new",
        "Fansly new transaction",
        "revenue",
        "handle_transaction_new",
        targets=(
            "provider_webhook_events",
            "provider_wallet_transactions",
        ),
        subject=("payload.id", "payload.transaction.id", "data.id"),
        retention=RetentionClass.FINANCIAL,
    ),
    _spec(
        "fansly.accounts.connected",
        "Fansly account connected",
        "account",
        "handle_account_connected",
        targets=("provider_webhook_events", "provider_connection_state"),
        subject=("account_id", "accountId", "payload.account.id"),
        retention=RetentionClass.SAFETY,
    ),
    _spec(
        "fansly.accounts.authentication_failed",
        "Fansly account authentication failed",
        "account",
        "handle_account_authentication_failed",
        targets=(
            "provider_webhook_events",
            "provider_circuit_breakers",
            "creator_settings",
            "provider_alerts",
        ),
        affects_send=True,
        subject=("account_id", "accountId", "payload.account.id"),
        retention=RetentionClass.SAFETY,
    ),
    _spec(
        "fansly.followers.new",
        "Fansly new follower",
        "lifecycle",
        "handle_follower_new",
        targets=("provider_webhook_events", "fans", "fan_relationships"),
        subject=("payload.user.id", "payload.fan.id", "data.id"),
    ),
    _spec(
        "fansly.followers.removed",
        "Fansly follower removed",
        "lifecycle",
        "handle_follower_removed",
        targets=("provider_webhook_events", "fans", "fan_relationships"),
        subject=("payload.user.id", "payload.fan.id", "data.id"),
    ),
    _spec(
        "fansly.subscriptions.expired",
        "Fansly subscription expired",
        "lifecycle",
        "handle_subscription_expired",
        targets=(
            "provider_webhook_events",
            "fans",
            "fan_subscriptions",
        ),
        subject=("payload.subscription.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.posts.liked",
        "Fansly post liked",
        "engagement",
        "ignore_post_liked",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.post.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.media.liked",
        "Fansly media liked",
        "engagement",
        "ignore_media_liked",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.media.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.media.purchased",
        "Fansly media purchased",
        "revenue",
        "handle_media_purchased",
        targets=(
            "provider_webhook_events",
            "purchase_events",
            "fan_revenue_events",
        ),
        subject=("payload.purchase.id", "payload.id", "data.id"),
        retention=RetentionClass.FINANCIAL,
    ),
    _spec(
        "fansly.payouts.created",
        "Fansly payout request created",
        "payout",
        "ignore_payout_created",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.payout.id", "payload.id", "data.id"),
        retention=RetentionClass.FINANCIAL,
    ),
    _spec(
        "fansly.payouts.updated",
        "Fansly payout request updated",
        "payout",
        "ignore_payout_updated",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.payout.id", "payload.id", "data.id"),
        retention=RetentionClass.FINANCIAL,
    ),
    _spec(
        "fansly.messages.reaction_added",
        "Fansly message reaction added",
        "engagement",
        "ignore_message_reaction_added",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.message.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.messages.reaction_removed",
        "Fansly message reaction removed",
        "engagement",
        "ignore_message_reaction_removed",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.message.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.posts.created",
        "Fansly post created",
        "content",
        "ignore_post_created",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.post.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.posts.updated",
        "Fansly post updated",
        "content",
        "ignore_post_updated",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.post.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.posts.deleted",
        "Fansly post deleted",
        "content",
        "ignore_post_deleted",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.post.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.posts.pinned",
        "Fansly post pinned",
        "content",
        "ignore_post_pinned",
        readiness=HandlerReadiness.IGNORED,
        ignored=True,
        subject=("payload.post.id", "payload.id", "data.id"),
    ),
    _spec(
        "fansly.stories.purchased",
        "Fansly story purchased",
        "revenue",
        "handle_story_purchased",
        targets=(
            "provider_webhook_events",
            "purchase_events",
            "fan_revenue_events",
        ),
        subject=("payload.purchase.id", "payload.id", "data.id"),
        retention=RetentionClass.FINANCIAL,
    ),
)

EVENT_REGISTRY: Mapping[str, FanslyEventSpec] = {
    spec.name: spec for spec in _SPECS
}

CORE_V1_DESIRED_EVENTS = frozenset(
    {
        "fansly.messages.received",
        "fansly.messages.sent",
        "fansly.messages.deleted",
        "fansly.messages.read",
        "fansly.accounts.connected",
        "fansly.accounts.authentication_failed",
        "fansly.transactions.new",
        "fansly.tips.received",
        "fansly.media.purchased",
        "fansly.stories.purchased",
        "fansly.subscriptions.new",
        "fansly.subscriptions.expired",
        "fansly.followers.new",
        "fansly.followers.removed",
    }
)

EVENT_PROFILES: Mapping[str, frozenset[str]] = {
    CORE_V1_PROFILE: CORE_V1_DESIRED_EVENTS,
}


def eligible_event_names(profile: str) -> tuple[str, ...]:
    """Return only desired events whose handlers are explicitly ready."""
    desired = EVENT_PROFILES.get(profile)
    if desired is None:
        raise ValueError(f"unknown webhook event profile: {profile}")
    return tuple(
        sorted(
            event_name
            for event_name in desired
            if EVENT_REGISTRY[event_name].handler_ready
        )
    )


def profile_blockers(profile: str) -> tuple[str, ...]:
    """Return desired events that cannot yet be registered safely."""
    desired = EVENT_PROFILES.get(profile)
    if desired is None:
        raise ValueError(f"unknown webhook event profile: {profile}")
    return tuple(
        sorted(
            event_name
            for event_name in desired
            if not EVENT_REGISTRY[event_name].handler_ready
        )
    )


def compare_live_catalog(
    live_events: Iterable[Mapping[str, object]],
) -> CatalogDrift:
    """Compare sanitized live ``value``/``description`` rows to the contract."""
    observed: dict[str, str] = {}
    for item in live_events:
        name = str(item.get("value") or item.get("name") or "").strip()
        if not name.startswith("fansly."):
            continue
        observed[name] = str(item.get("description") or "").strip()

    expected_names = set(EVENT_REGISTRY)
    observed_names = set(observed)
    description_mismatches = tuple(
        sorted(
            name
            for name in expected_names & observed_names
            if observed[name] != EVENT_REGISTRY[name].description
        )
    )
    return CatalogDrift(
        missing=tuple(sorted(expected_names - observed_names)),
        unexpected=tuple(sorted(observed_names - expected_names)),
        description_mismatches=description_mismatches,
    )
