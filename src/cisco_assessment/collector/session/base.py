"""Interactive network-session contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SessionCommandResult:
    raw: bytes


class NetworkSession(Protocol):
    def open(self) -> None: ...

    def execute(self, command: str, *, timeout: float) -> SessionCommandResult: ...

    def close(self) -> None: ...
