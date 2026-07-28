"""Explicit process roles for separating API, worker, and scheduler duties."""

from __future__ import annotations

from enum import Enum


class ServiceRole(str, Enum):
    ALL = "all"
    API = "api"
    WORKER = "worker"
    SCHEDULER = "scheduler"

    @classmethod
    def parse(cls, value: str | None) -> "ServiceRole":
        normalized = str(value or cls.ALL.value).strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            supported = ", ".join(role.value for role in cls)
            raise ValueError(
                f"invalid SERVICE_ROLE {normalized!r}; expected {supported}"
            ) from exc

    @property
    def serves_api(self) -> bool:
        return self in {self.ALL, self.API}

    @property
    def runs_reply_workers(self) -> bool:
        return self in {self.ALL, self.WORKER}

    @property
    def runs_scheduler(self) -> bool:
        return self in {self.ALL, self.SCHEDULER}
