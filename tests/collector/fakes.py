from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
import hashlib
from cisco_switch_assessment.catalog import CommandSpec
from cisco_switch_assessment.collector.session.base import SessionCommandResult
from cisco_switch_assessment.models import RawCommandOutput, utcnow

class FakeSession:
    def __init__(self, result: bytes | Exception) -> None:
        self.result, self.calls = result, []
    def execute(self, command: str, *, timeout: float) -> SessionCommandResult:
        self.calls.append((command, timeout))
        if isinstance(self.result, Exception): raise self.result
        return SessionCommandResult(raw=self.result)

@dataclass
class InMemoryRawRepository:
    saved: bytes | None = None
    def save(self, *, run_id: str, device_id: str, execution_id: UUID, command: CommandSpec, content: bytes) -> RawCommandOutput:
        self.saved = content
        return RawCommandOutput(id=RawCommandOutput.new_id(), command_execution_id=execution_id, storage_path=Path(f"memory://{run_id}/{device_id}/{command.id.value}"), size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), captured_at=utcnow())
