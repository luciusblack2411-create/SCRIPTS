import pytest
from pydantic import ValidationError

from cisco_assessment.catalog import (
    CommandCatalog,
    CommandCategory,
    CommandDefinition,
    CommandId,
    CommandRequirement,
    CommandVariant,
    NormalizedModelId,
    ParserId,
)
from cisco_assessment.models.enums import PlatformFamily


def _definition(command_id: CommandId = CommandId.SYSTEM_VERSION) -> CommandDefinition:
    return CommandDefinition(
        command_id=command_id,
        category=CommandCategory.SYSTEM,
        purpose="Collect version facts.",
        normalized_model=NormalizedModelId.DEVICE_INFO,
        requirement=CommandRequirement.REQUIRED,
        variants={
            PlatformFamily.IOS: CommandVariant(
                cli_command="show version",
                parser_id=ParserId.IOS_SHOW_VERSION_V1,
            )
        },
    )


def test_variant_normalizes_cli_whitespace() -> None:
    variant = CommandVariant(
        cli_command="  show version  ",
        parser_id=ParserId.IOS_SHOW_VERSION_V1,
    )
    assert variant.cli_command == "show version"


def test_variant_rejects_non_show_command() -> None:
    with pytest.raises(ValidationError):
        CommandVariant(
            cli_command="configure terminal",
            parser_id=ParserId.IOS_SHOW_VERSION_V1,
        )


def test_definition_rejects_unknown_platform_variant() -> None:
    with pytest.raises(ValidationError):
        CommandDefinition(
            command_id=CommandId.SYSTEM_VERSION,
            category=CommandCategory.SYSTEM,
            purpose="Collect version facts.",
            normalized_model=NormalizedModelId.DEVICE_INFO,
            requirement=CommandRequirement.REQUIRED,
            variants={
                PlatformFamily.UNKNOWN: CommandVariant(
                    cli_command="show version",
                    parser_id=ParserId.IOS_SHOW_VERSION_V1,
                )
            },
        )


def test_catalog_rejects_duplicate_command_ids() -> None:
    with pytest.raises(ValidationError):
        CommandCatalog(commands=(_definition(), _definition()))


def test_catalog_resolve_returns_none_for_unsupported_platform() -> None:
    catalog = CommandCatalog(commands=(_definition(),))
    assert catalog.resolve(CommandId.SYSTEM_VERSION, PlatformFamily.NX_OS) is None
