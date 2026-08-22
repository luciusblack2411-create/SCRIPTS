"""Structured failures for end-to-end assessment orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class RunnerStage(StrEnum):
    """Stable stages used to classify orchestration failures."""

    VALIDATION = "validation"
    COLLECTION = "collection"
    PARSING = "parsing"
    ASSESSMENT = "assessment"
    REPORTING = "reporting"
    PERSISTENCE = "persistence"


@dataclass(frozen=True, slots=True)
class RunnerFailure:
    """Serializable failure metadata without embedding arbitrary exception objects."""

    stage: RunnerStage
    error_type: str
    message: str
    command_execution_id: UUID | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "stage": self.stage.value,
            "error_type": self.error_type,
            "message": self.message,
            "command_execution_id": (
                str(self.command_execution_id) if self.command_execution_id is not None else None
            ),
        }
