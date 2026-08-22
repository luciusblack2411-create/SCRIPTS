import pytest

from cisco_assessment.catalog import COMMAND_CATALOG_V0_1, CommandCatalog, CommandId
from cisco_assessment.catalog.enums import (
    CommandCategory,
    CommandRequirement,
    NormalizedModelId,
    ParserId,
)
from cisco_assessment.catalog.models import CommandDefinition, CommandVariant
from cisco_assessment.collector.exceptions import CommandPolicyError
from cisco_assessment.collector.policy import ReadOnlyPolicy
from cisco_assessment.models import PlatformFamily


def test_show_version_from_current_catalog_is_authorized() -> None:
    authorized = ReadOnlyPolicy().authorize(
        catalog=COMMAND_CATALOG_V0_1,
        command_id=CommandId.SYSTEM_VERSION,
        platform=PlatformFamily.IOS_XE,
    )
    assert authorized.variant.cli_command == "show version"


@pytest.mark.parametrize(
    "cli",
    ["show version; reload", "show version | redirect flash:x", "show version && reload"],
)
def test_policy_rejects_chained_or_side_effect_show_commands(cli: str) -> None:
    variant = CommandVariant(cli_command=cli, parser_id=ParserId.IOS_SHOW_VERSION_V1)
    definition = CommandDefinition(
        command_id=CommandId.SYSTEM_VERSION,
        category=CommandCategory.SYSTEM,
        purpose="unsafe test",
        normalized_model=NormalizedModelId.DEVICE_INFO,
        requirement=CommandRequirement.REQUIRED,
        variants={PlatformFamily.IOS_XE: variant},
    )
    catalog = CommandCatalog(commands=(definition,))

    with pytest.raises(CommandPolicyError):
        ReadOnlyPolicy().authorize(
            catalog=catalog,
            command_id=CommandId.SYSTEM_VERSION,
            platform=PlatformFamily.IOS_XE,
        )
