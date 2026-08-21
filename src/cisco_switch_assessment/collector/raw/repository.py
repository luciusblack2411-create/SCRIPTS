from typing import Protocol
from uuid import UUID
from cisco_switch_assessment.catalog import CommandSpec
from cisco_switch_assessment.models import RawCommandOutput

class RawRepository(Protocol):
    def save(self, *, run_id: str, device_id: str, execution_id: UUID, command: CommandSpec, content: bytes) -> RawCommandOutput: ...
