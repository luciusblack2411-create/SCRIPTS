from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from cisco_assessment.collector.session.base import SessionCommandResult
from cisco_assessment.models import RawCommandOutput
from cisco_assessment.raw.repository import PersistedRawOutput


class FakeSession:
    def __init__(self, result: bytes | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, float]] = []

    def execute(self, command: str, *, timeout: float) -> SessionCommandResult:
        self.calls.append((command, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return SessionCommandResult(raw=self.result)


@dataclass
class InMemoryRawRepository:
    saved: bytes | None = None
    truncated: bool = False

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
    ) -> PersistedRawOutput:
        del device_id, sequence
        self.saved = content
        self.truncated = is_truncated
        try:
            text, encoding = content.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, encoding = content.decode("latin-1"), "latin-1"
        output = RawCommandOutput.from_text(
            command_execution_id=command_execution_id,
            content=text,
            encoding=encoding,
            is_truncated=is_truncated,
        )
        assert output.sha256 == hashlib.sha256(content).hexdigest()
        path = Path(f"/memory/{assessment_run_id}/{command_key}.raw")
        return PersistedRawOutput(output=output, path=path)
