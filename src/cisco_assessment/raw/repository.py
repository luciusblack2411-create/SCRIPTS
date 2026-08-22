"""RAW output persistence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from cisco_assessment.models import RawCommandOutput


@dataclass(frozen=True, slots=True)
class PersistedRawOutput:
    """Canonical RAW model plus its storage location."""

    output: RawCommandOutput
    path: Path


class RawRepository(Protocol):
    def save(
        self,
        *,
        assessment_run_id: UUID,
        device_id: UUID,
        command_execution_id: UUID,
        command_key: str,
        sequence: int,
        content: bytes,
        is_truncated: bool = False,
    ) -> PersistedRawOutput: ...
