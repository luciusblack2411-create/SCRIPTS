"""Typed assessment plans for ordered multi-command orchestration."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cisco_assessment.catalog import CommandId


class AssessmentPlanItem(BaseModel):
    """One ordered command reference inside an assessment plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: CommandId


class AssessmentPlan(BaseModel):
    """Immutable ordered command sequence resolved against the Command Catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    commands: tuple[AssessmentPlanItem, ...]

    @field_validator("plan_id", "version")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("plan_id and version must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_commands(self) -> Self:
        if not self.commands:
            raise ValueError("assessment plan must contain at least one command")
        command_ids = [item.command_id for item in self.commands]
        if len(command_ids) != len(set(command_ids)):
            raise ValueError("assessment plan must not contain duplicate command IDs")
        return self

    @property
    def command_ids(self) -> tuple[CommandId, ...]:
        """Return the plan's command IDs in deterministic execution order."""
        return tuple(item.command_id for item in self.commands)


SHOW_VERSION_PLAN_V0_2 = AssessmentPlan(
    plan_id="show-version",
    version="0.2",
    commands=(AssessmentPlanItem(command_id=CommandId.SYSTEM_VERSION),),
)

HARDWARE_INVENTORY_PLAN_V0_1 = AssessmentPlan(
    plan_id="hardware-inventory",
    version="0.1",
    commands=(
        AssessmentPlanItem(command_id=CommandId.SYSTEM_VERSION),
        AssessmentPlanItem(command_id=CommandId.SYSTEM_INVENTORY),
    ),
)
