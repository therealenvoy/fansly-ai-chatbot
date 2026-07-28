"""Durable fan contact permissions and conservative opt-out detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, and_, insert, select, update

from .persistence.schema import FAN_CONTACT_POLICIES


_OPT_OUT = re.compile(
    r"(?:^(?:please\s+)?stop[.!]?$|(?:^|\b)(?:"
    r"stop\s+(?:messaging|texting|contacting)\s+me|"
    r"unsubscribe|do\s+not\s+(?:message|text|contact)\s+me|"
    r"don['\u2019]?t\s+(?:message|text|contact)\s+me|"
    r"leave\s+me\s+alone)(?:\b|$))",
    re.IGNORECASE,
)


def is_opt_out_message(content: str) -> bool:
    return bool(_OPT_OUT.search(str(content or "").strip()))


@dataclass(frozen=True)
class ContactPolicy:
    creator_id: str
    fan_id: str
    do_not_contact: bool
    paused_until: datetime | None
    cooldown_until: datetime | None
    version: int
    source: str
    reason: str | None


class ContactPolicyRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, creator_id: str, fan_id: str) -> ContactPolicy | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(FAN_CONTACT_POLICIES).where(
                    and_(
                        FAN_CONTACT_POLICIES.c.creator_id == creator_id,
                        FAN_CONTACT_POLICIES.c.fan_id == fan_id,
                    )
                )
            ).mappings().first()
        return self._coerce(row) if row else None

    def version(self, creator_id: str, fan_id: str) -> int:
        policy = self.get(creator_id, fan_id)
        return policy.version if policy else 0

    def record_opt_out(
        self,
        creator_id: str,
        fan_id: str,
        *,
        source: str = "inbound_message",
    ) -> ContactPolicy:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(FAN_CONTACT_POLICIES)
                .where(
                    and_(
                        FAN_CONTACT_POLICIES.c.creator_id == creator_id,
                        FAN_CONTACT_POLICIES.c.fan_id == fan_id,
                    )
                )
                .with_for_update()
            ).mappings().first()
            if row is None:
                connection.execute(
                    insert(FAN_CONTACT_POLICIES).values(
                        creator_id=creator_id,
                        fan_id=fan_id,
                        do_not_contact=True,
                        paused_until=None,
                        cooldown_until=None,
                        version=1,
                        source=source[:64],
                        reason="fan_opt_out",
                        updated_at=now,
                    )
                )
            else:
                connection.execute(
                    update(FAN_CONTACT_POLICIES)
                    .where(
                        and_(
                            FAN_CONTACT_POLICIES.c.creator_id == creator_id,
                            FAN_CONTACT_POLICIES.c.fan_id == fan_id,
                        )
                    )
                    .values(
                        do_not_contact=True,
                        version=int(row["version"]) + 1,
                        source=source[:64],
                        reason="fan_opt_out",
                        updated_at=now,
                    )
                )
        policy = self.get(creator_id, fan_id)
        if policy is None:
            raise RuntimeError("contact policy persistence failed")
        return policy

    @staticmethod
    def _coerce(row) -> ContactPolicy:
        return ContactPolicy(
            creator_id=row["creator_id"],
            fan_id=row["fan_id"],
            do_not_contact=bool(row["do_not_contact"]),
            paused_until=row["paused_until"],
            cooldown_until=row["cooldown_until"],
            version=int(row["version"]),
            source=row["source"],
            reason=row["reason"],
        )
