"""Durable provider credit accounting and a billing circuit breaker."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Engine, and_, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from .persistence.schema import (
    PROVIDER_CIRCUIT_BREAKERS,
    PROVIDER_CREDIT_BUDGETS,
    PROVIDER_CREDIT_EVENTS,
    PROVIDER_CREDIT_RESERVATIONS,
)


_worker_name: ContextVar[str] = ContextVar(
    "provider_credit_worker",
    default="unclassified",
)


@contextmanager
def provider_worker(name: str):
    """Attribute provider calls to a bounded, non-sensitive worker name."""
    token = _worker_name.set(str(name or "unclassified")[:64])
    try:
        yield
    finally:
        _worker_name.reset(token)


class ProviderCreditError(RuntimeError):
    """Base class for local credit-control failures."""


class ProviderCircuitOpen(ProviderCreditError):
    """Paid provider traffic is blocked pending explicit operator reset."""


class ProviderBudgetExceeded(ProviderCreditError):
    """The configured local credit budget cannot fund this request."""


@dataclass(frozen=True)
class ProviderCreditSettings:
    monthly_limit: int = 20_000
    daily_read_limit: int = 50
    monthly_send_reserve: int = 15_000
    monthly_emergency_reserve: int = 2_000

    def __post_init__(self) -> None:
        values = (
            self.monthly_limit,
            self.daily_read_limit,
            self.monthly_send_reserve,
            self.monthly_emergency_reserve,
        )
        if any(value < 0 for value in values):
            raise ValueError("provider credit limits cannot be negative")
        if (
            self.monthly_send_reserve + self.monthly_emergency_reserve
            > self.monthly_limit
        ):
            raise ValueError("provider credit reserves exceed monthly limit")


@dataclass(frozen=True)
class CreditReservation:
    id: str
    operation: str
    worker: str
    request_class: str
    credits: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _day_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


class ProviderCreditGovernor:
    """Reserve before every paid call, record actual usage, and fail closed."""

    def __init__(
        self,
        engine: Engine,
        *,
        creator_id: str,
        provider: str = "apifansly",
        settings: ProviderCreditSettings | None = None,
    ) -> None:
        self.engine = engine
        self.creator_id = creator_id
        self.provider = provider
        self.settings = settings or ProviderCreditSettings()

    def is_circuit_open(self) -> bool:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(PROVIDER_CIRCUIT_BREAKERS.c.is_open).where(
                    and_(
                        PROVIDER_CIRCUIT_BREAKERS.c.creator_id
                        == self.creator_id,
                        PROVIDER_CIRCUIT_BREAKERS.c.provider
                        == self.provider,
                    )
                )
            ).scalar_one_or_none()
        return bool(value)

    def open_circuit(self, reason_code: str) -> None:
        now = _now()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(PROVIDER_CIRCUIT_BREAKERS)
                .where(
                    and_(
                        PROVIDER_CIRCUIT_BREAKERS.c.creator_id
                        == self.creator_id,
                        PROVIDER_CIRCUIT_BREAKERS.c.provider
                        == self.provider,
                    )
                )
                .values(
                    is_open=True,
                    reason_code=str(reason_code)[:64],
                    opened_at=now,
                    operator_reset_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount == 0:
                connection.execute(
                    insert(PROVIDER_CIRCUIT_BREAKERS).values(
                        creator_id=self.creator_id,
                        provider=self.provider,
                        is_open=True,
                        reason_code=str(reason_code)[:64],
                        opened_at=now,
                        operator_reset_at=None,
                        updated_at=now,
                    )
                )

    def reset_circuit(self) -> None:
        """Explicit operator action; successful requests never auto-reset it."""
        now = _now()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(PROVIDER_CIRCUIT_BREAKERS)
                .where(
                    and_(
                        PROVIDER_CIRCUIT_BREAKERS.c.creator_id
                        == self.creator_id,
                        PROVIDER_CIRCUIT_BREAKERS.c.provider
                        == self.provider,
                    )
                )
                .values(
                    is_open=False,
                    reason_code=None,
                    operator_reset_at=now,
                    updated_at=now,
                )
            )
            if result.rowcount == 0:
                connection.execute(
                    insert(PROVIDER_CIRCUIT_BREAKERS).values(
                        creator_id=self.creator_id,
                        provider=self.provider,
                        is_open=False,
                        reason_code=None,
                        opened_at=None,
                        operator_reset_at=now,
                        updated_at=now,
                    )
                )

    def reserve(
        self,
        operation: str,
        *,
        request_class: str,
        credits: int = 1,
        allow_when_open: bool = False,
    ) -> CreditReservation:
        if credits < 0:
            raise ValueError("reserved credits cannot be negative")
        operation = str(operation or "unknown")[:64]
        request_class = str(request_class or "read")[:32]
        worker = _worker_name.get()
        if credits == 0:
            return CreditReservation(
                id=str(uuid4()),
                operation=operation,
                worker=worker,
                request_class=request_class,
                credits=0,
            )
        if not allow_when_open and self.is_circuit_open():
            self.record_blocked(
                operation,
                request_class=request_class,
                detail_code="circuit_open",
            )
            raise ProviderCircuitOpen(
                "Provider credit circuit is open; explicit operator reset required"
            )

        reservation = CreditReservation(
            id=str(uuid4()),
            operation=operation,
            worker=worker,
            request_class=request_class,
            credits=credits,
        )
        now = _now()
        with self.engine.begin() as connection:
            rows = self._budget_rows(now, request_class=request_class)
            for period_kind, period_start, category, limit in rows:
                self._ensure_budget_row(
                    connection,
                    period_kind=period_kind,
                    period_start=period_start,
                    request_class=category,
                    credit_limit=limit,
                    now=now,
                )
                row = connection.execute(
                    select(
                        PROVIDER_CREDIT_BUDGETS.c.used_credits,
                        PROVIDER_CREDIT_BUDGETS.c.reserved_credits,
                    )
                    .where(
                        and_(
                            PROVIDER_CREDIT_BUDGETS.c.creator_id
                            == self.creator_id,
                            PROVIDER_CREDIT_BUDGETS.c.provider
                            == self.provider,
                            PROVIDER_CREDIT_BUDGETS.c.period_kind
                            == period_kind,
                            PROVIDER_CREDIT_BUDGETS.c.period_start
                            == period_start,
                            PROVIDER_CREDIT_BUDGETS.c.request_class
                            == category,
                        )
                    )
                    .with_for_update()
                ).one()
                if row.used_credits + row.reserved_credits + credits > limit:
                    self._insert_event(
                        connection,
                        operation=operation,
                        worker=worker,
                        request_class=request_class,
                        method="LOCAL",
                        result="blocked",
                        reserved_credits=0,
                        used_credits=0,
                        detail_code=f"{category}_budget",
                    )
                    raise ProviderBudgetExceeded(
                        f"Provider credit budget exhausted for {category}"
                    )
            for period_kind, period_start, category, _ in rows:
                connection.execute(
                    update(PROVIDER_CREDIT_BUDGETS)
                    .where(
                        and_(
                            PROVIDER_CREDIT_BUDGETS.c.creator_id
                            == self.creator_id,
                            PROVIDER_CREDIT_BUDGETS.c.provider
                            == self.provider,
                            PROVIDER_CREDIT_BUDGETS.c.period_kind
                            == period_kind,
                            PROVIDER_CREDIT_BUDGETS.c.period_start
                            == period_start,
                            PROVIDER_CREDIT_BUDGETS.c.request_class
                            == category,
                        )
                    )
                    .values(
                        reserved_credits=(
                            PROVIDER_CREDIT_BUDGETS.c.reserved_credits + credits
                        ),
                        updated_at=now,
                    )
                )
            connection.execute(
                insert(PROVIDER_CREDIT_RESERVATIONS).values(
                    id=reservation.id,
                    creator_id=self.creator_id,
                    provider=self.provider,
                    operation=operation,
                    worker=worker,
                    request_class=request_class,
                    reserved_credits=credits,
                    used_credits=None,
                    status="reserved",
                    created_at=now,
                    finalized_at=None,
                )
            )
        return reservation

    def finalize(
        self,
        reservation: CreditReservation,
        *,
        method: str,
        result: str,
        status_code: int | None,
        used_credits: int | None,
        balance: int | None = None,
        retry_count: int = 0,
        detail_code: str | None = None,
    ) -> None:
        actual = (
            reservation.credits
            if used_credits is None
            else max(0, int(used_credits))
        )
        now = _now()
        with self.engine.begin() as connection:
            if reservation.credits:
                for period_kind, period_start, category, _ in self._budget_rows(
                    now,
                    request_class=reservation.request_class,
                ):
                    connection.execute(
                        update(PROVIDER_CREDIT_BUDGETS)
                        .where(
                            and_(
                                PROVIDER_CREDIT_BUDGETS.c.creator_id
                                == self.creator_id,
                                PROVIDER_CREDIT_BUDGETS.c.provider
                                == self.provider,
                                PROVIDER_CREDIT_BUDGETS.c.period_kind
                                == period_kind,
                                PROVIDER_CREDIT_BUDGETS.c.period_start
                                == period_start,
                                PROVIDER_CREDIT_BUDGETS.c.request_class
                                == category,
                            )
                        )
                        .values(
                            reserved_credits=(
                                PROVIDER_CREDIT_BUDGETS.c.reserved_credits
                                - reservation.credits
                            ),
                            used_credits=(
                                PROVIDER_CREDIT_BUDGETS.c.used_credits + actual
                            ),
                            updated_at=now,
                        )
                    )
                connection.execute(
                    update(PROVIDER_CREDIT_RESERVATIONS)
                    .where(
                        PROVIDER_CREDIT_RESERVATIONS.c.id == reservation.id
                    )
                    .values(
                        used_credits=actual,
                        status="finalized",
                        finalized_at=now,
                    )
                )
            self._insert_event(
                connection,
                operation=reservation.operation,
                worker=reservation.worker,
                request_class=reservation.request_class,
                method=method,
                result=result,
                status_code=status_code,
                reserved_credits=reservation.credits,
                used_credits=actual,
                balance=balance,
                retry_count=retry_count,
                detail_code=detail_code,
            )

    def record_blocked(
        self,
        operation: str,
        *,
        request_class: str,
        detail_code: str,
    ) -> None:
        with self.engine.begin() as connection:
            self._insert_event(
                connection,
                operation=str(operation or "unknown")[:64],
                worker=_worker_name.get(),
                request_class=str(request_class or "read")[:32],
                method="LOCAL",
                result="blocked",
                reserved_credits=0,
                used_credits=0,
                detail_code=detail_code,
            )

    def snapshot(self) -> dict[str, object]:
        now = _now()
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(PROVIDER_CREDIT_BUDGETS).where(
                    and_(
                        PROVIDER_CREDIT_BUDGETS.c.creator_id
                        == self.creator_id,
                        PROVIDER_CREDIT_BUDGETS.c.provider == self.provider,
                        PROVIDER_CREDIT_BUDGETS.c.period_start.in_(
                            [_day_start(now), _month_start(now)]
                        ),
                    )
                )
            ).mappings()
            budgets = [
                {
                    "period_kind": row["period_kind"],
                    "request_class": row["request_class"],
                    "limit": row["credit_limit"],
                    "used": row["used_credits"],
                    "reserved": row["reserved_credits"],
                }
                for row in rows
            ]
            usage_rows = connection.execute(
                select(
                    PROVIDER_CREDIT_EVENTS.c.worker,
                    PROVIDER_CREDIT_EVENTS.c.request_class,
                    func.count(PROVIDER_CREDIT_EVENTS.c.id).label(
                        "request_count"
                    ),
                    func.coalesce(
                        func.sum(
                            PROVIDER_CREDIT_EVENTS.c.used_credits
                        ),
                        0,
                    ).label("used_credits"),
                )
                .where(
                    and_(
                        PROVIDER_CREDIT_EVENTS.c.creator_id
                        == self.creator_id,
                        PROVIDER_CREDIT_EVENTS.c.provider
                        == self.provider,
                        PROVIDER_CREDIT_EVENTS.c.created_at
                        >= _month_start(now),
                    )
                )
                .group_by(
                    PROVIDER_CREDIT_EVENTS.c.worker,
                    PROVIDER_CREDIT_EVENTS.c.request_class,
                )
            ).mappings().all()
        usage_by_class = {
            "provider_read": {"requests": 0, "credits": 0},
            "provider_send": {"requests": 0, "credits": 0},
            "registration_control": {"requests": 0, "credits": 0},
            "reconciliation": {"requests": 0, "credits": 0},
        }
        for row in usage_rows:
            request_class = row["request_class"]
            if row["worker"] == "provider-reconciliation":
                category = "reconciliation"
            elif request_class in {"send", "emergency"}:
                category = "provider_send"
            elif request_class == "control":
                category = "registration_control"
            else:
                category = "provider_read"
            usage_by_class[category]["requests"] += int(
                row["request_count"]
            )
            usage_by_class[category]["credits"] += int(
                row["used_credits"]
            )
        return {
            "provider": self.provider,
            "circuit_open": self.is_circuit_open(),
            "budgets": budgets,
            "usage_period": "current_month",
            "usage_by_class": usage_by_class,
        }

    def _budget_rows(
        self,
        now: datetime,
        *,
        request_class: str,
    ) -> list[tuple[str, datetime, str, int]]:
        monthly_usable = self.settings.monthly_limit
        if request_class not in {"send", "emergency"}:
            monthly_usable -= (
                self.settings.monthly_send_reserve
                + self.settings.monthly_emergency_reserve
            )
        elif request_class == "send":
            monthly_usable -= self.settings.monthly_emergency_reserve
        rows = [
            ("month", _month_start(now), "total", max(0, monthly_usable)),
        ]
        if request_class not in {"send", "emergency", "control"}:
            rows.append(
                (
                    "day",
                    _day_start(now),
                    "read",
                    self.settings.daily_read_limit,
                )
            )
        return rows

    def _ensure_budget_row(
        self,
        connection,
        *,
        period_kind: str,
        period_start: datetime,
        request_class: str,
        credit_limit: int,
        now: datetime,
    ) -> None:
        values = {
            "creator_id": self.creator_id,
            "provider": self.provider,
            "period_kind": period_kind,
            "period_start": period_start,
            "request_class": request_class,
            "credit_limit": credit_limit,
            "used_credits": 0,
            "reserved_credits": 0,
            "updated_at": now,
        }
        try:
            with connection.begin_nested():
                connection.execute(
                    insert(PROVIDER_CREDIT_BUDGETS).values(**values)
                )
        except IntegrityError:
            pass
        connection.execute(
            update(PROVIDER_CREDIT_BUDGETS)
            .where(
                and_(
                    PROVIDER_CREDIT_BUDGETS.c.creator_id == self.creator_id,
                    PROVIDER_CREDIT_BUDGETS.c.provider == self.provider,
                    PROVIDER_CREDIT_BUDGETS.c.period_kind == period_kind,
                    PROVIDER_CREDIT_BUDGETS.c.period_start == period_start,
                    PROVIDER_CREDIT_BUDGETS.c.request_class == request_class,
                )
            )
            .values(credit_limit=credit_limit, updated_at=now)
        )

    def _insert_event(
        self,
        connection,
        *,
        operation: str,
        worker: str,
        request_class: str,
        method: str,
        result: str,
        reserved_credits: int,
        used_credits: int | None,
        status_code: int | None = None,
        balance: int | None = None,
        retry_count: int = 0,
        detail_code: str | None = None,
    ) -> None:
        connection.execute(
            insert(PROVIDER_CREDIT_EVENTS).values(
                creator_id=self.creator_id,
                provider=self.provider,
                operation=operation,
                worker=worker,
                request_class=request_class,
                method=method,
                result=result,
                status_code=status_code,
                reserved_credits=reserved_credits,
                used_credits=used_credits,
                balance=balance,
                retry_count=retry_count,
                detail_code=(
                    str(detail_code)[:64] if detail_code else None
                ),
                created_at=_now(),
            )
        )
