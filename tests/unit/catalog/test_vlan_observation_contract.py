from cisco_assessment.catalog import (
    COMMAND_CATALOG_V0_1,
    CommandCategory,
    CommandId,
    CommandRequirement,
    NormalizedModelId,
    ParserId,
    UnsupportedPlatformPolicy,
)
from cisco_assessment.models.enums import PlatformFamily


def test_vlan_brief_command_id_is_stable() -> None:
    assert CommandId.VLANS_BRIEF.value == "vlans.brief"


def test_vlan_brief_contract_matches_vlan_observation_v0_1() -> None:
    definition = COMMAND_CATALOG_V0_1.get(CommandId.VLANS_BRIEF)

    assert definition.category is CommandCategory.VLANS
    assert definition.normalized_model is NormalizedModelId.VLAN_OBSERVATION
    assert definition.requirement is CommandRequirement.REQUIRED
    assert definition.unsupported_platform_policy is UnsupportedPlatformPolicy.SKIP
    assert definition.supported_platforms == frozenset(
        {PlatformFamily.IOS, PlatformFamily.IOS_XE}
    )

    for platform in (PlatformFamily.IOS, PlatformFamily.IOS_XE):
        variant = COMMAND_CATALOG_V0_1.resolve(CommandId.VLANS_BRIEF, platform)
        assert variant is not None
        assert variant.cli_command == "show vlan brief"
        assert variant.parser_id is ParserId.IOS_SHOW_VLAN_BRIEF_V1


def test_vlan_brief_has_no_unsupported_platform_variant() -> None:
    assert COMMAND_CATALOG_V0_1.resolve(CommandId.VLANS_BRIEF, PlatformFamily.NX_OS) is None
    assert COMMAND_CATALOG_V0_1.resolve(CommandId.VLANS_BRIEF, PlatformFamily.UNKNOWN) is None


def test_vlan_brief_and_catalog_remain_read_only() -> None:
    definition = COMMAND_CATALOG_V0_1.get(CommandId.VLANS_BRIEF)
    assert definition.read_only is True

    for command in COMMAND_CATALOG_V0_1.commands:
        assert command.read_only is True
        for variant in command.variants.values():
            assert variant.cli_command.lower().startswith("show ")
