from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cisco_switch_assessment.models import Platform


class CommandId(StrEnum):
    SHOW_VERSION = "system.show_version"


class ExecutionClass(StrEnum):
    QUERY = "query"
    SESSION_CONTROL = "session_control"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    id: CommandId
    cli: str
    platforms: frozenset[Platform]
    purpose: str
    execution_class: ExecutionClass = ExecutionClass.QUERY
    required: bool = True
    timeout_seconds: float = 30.0

    def supports(self, platform: Platform) -> bool:
        return platform in self.platforms


class CommandCatalog:
    def __init__(self, commands: tuple[CommandSpec, ...]) -> None:
        self._commands = {command.id: command for command in commands}
        if len(self._commands) != len(commands):
            raise ValueError("duplicate command ids in catalog")

    def get(self, command_id: CommandId) -> CommandSpec:
        try:
            return self._commands[command_id]
        except KeyError as exc:
            raise KeyError(f"command not found in catalog: {command_id}") from exc

    def contains(self, spec: CommandSpec) -> bool:
        return self._commands.get(spec.id) == spec


MVP_COMMAND_CATALOG = CommandCatalog((CommandSpec(id=CommandId.SHOW_VERSION, cli="show version", platforms=frozenset({Platform.IOS, Platform.IOS_XE}), purpose="Collect device software and hardware version information.", timeout_seconds=30.0),))
