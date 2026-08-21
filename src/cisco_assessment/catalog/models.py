"""Pydantic models for read-only command catalog definitions."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from cisco_assessment.models.base import DomainModel
from cisco_assessment.models.enums import PlatformFamily

from .enums import (
    CommandCategory,
    CommandId,
    CommandRequirement,
    NormalizedModelId,
    ParserId,
    UnsupportedPlatformPolicy,
)


class CommandVariant(DomainModel):
    """Platform-specific CLI and parser metadata for one semantic command."""

    cli_command: str = Field(min_length=1)
    parser_id: ParserId

    @field_validator("cli_command")
    @classmethod
    def validate_read_only_cli(cls, value: str) -> str:
        command = value.strip()
        if "\n" in command or "\r" in command:
            raise ValueError("cli_command must be a single command")
        if not command.lower().startswith("show "):
            raise ValueError("command catalog v0.1 only permits read-only 'show' commands")
        return command


class CommandDefinition(DomainModel):
    """Platform-neutral definition of a stable collection intent."""

    command_id: CommandId
    category: CommandCategory
    purpose: str = Field(min_length=1)
    normalized_model: NormalizedModelId
    requirement: CommandRequirement
    variants: dict[PlatformFamily, CommandVariant]
    read_only: Literal[True] = True
    sensitive_output: bool = False
    unsupported_platform_policy: UnsupportedPlatformPolicy = UnsupportedPlatformPolicy.SKIP

    @field_validator("purpose")
    @classmethod
    def normalize_purpose(cls, value: str) -> str:
        purpose = value.strip()
        if not purpose:
            raise ValueError("purpose must not be blank")
        return purpose

    @model_validator(mode="after")
    def validate_variants(self) -> Self:
        if not self.variants:
            raise ValueError("at least one platform variant is required")
        if PlatformFamily.UNKNOWN in self.variants:
            raise ValueError("UNKNOWN cannot define an executable command variant")
        return self

    @property
    def supported_platforms(self) -> frozenset[PlatformFamily]:
        return frozenset(self.variants)


class CommandCatalog(DomainModel):
    """Versioned collection of command definitions with deterministic resolution."""

    catalog_version: Literal["0.1"] = "0.1"
    commands: tuple[CommandDefinition, ...]

    @model_validator(mode="after")
    def validate_unique_command_ids(self) -> Self:
        command_ids = [definition.command_id for definition in self.commands]
        if len(command_ids) != len(set(command_ids)):
            raise ValueError("command_id values must be unique within a catalog")
        return self

    def get(self, command_id: CommandId) -> CommandDefinition:
        for definition in self.commands:
            if definition.command_id == command_id:
                return definition
        raise KeyError(command_id)

    def resolve(self, command_id: CommandId, platform: PlatformFamily) -> CommandVariant | None:
        return self.get(command_id).variants.get(platform)

    def for_platform(
        self,
        platform: PlatformFamily,
        requirement: CommandRequirement | None = None,
    ) -> tuple[CommandDefinition, ...]:
        return tuple(
            definition
            for definition in self.commands
            if platform in definition.variants
            and (requirement is None or definition.requirement == requirement)
        )
