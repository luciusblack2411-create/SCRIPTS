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


def test_mvp_catalog_contains_expected_command_count() -> None:
    assert len(COMMAND_CATALOG_V0_1.commands) == 20


def test_mvp_catalog_has_14_required_and_6_optional_commands() -> None:
    required = COMMAND_CATALOG_V0_1.for_platform(
        PlatformFamily.IOS_XE,
        CommandRequirement.REQUIRED,
    )
    optional = COMMAND_CATALOG_V0_1.for_platform(
        PlatformFamily.IOS_XE,
        CommandRequirement.OPTIONAL,
    )
    assert len(required) == 14
    assert len(optional) == 6


def test_every_mvp_command_supports_ios_and_ios_xe() -> None:
    expected = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})
    for definition in COMMAND_CATALOG_V0_1.commands:
        assert definition.supported_platforms == expected


def test_nx_os_is_known_but_has_no_executable_mvp_variants() -> None:
    assert COMMAND_CATALOG_V0_1.for_platform(PlatformFamily.NX_OS) == ()
    assert COMMAND_CATALOG_V0_1.resolve(CommandId.SYSTEM_VERSION, PlatformFamily.NX_OS) is None


def test_show_version_contract_is_stable() -> None:
    definition = COMMAND_CATALOG_V0_1.get(CommandId.SYSTEM_VERSION)
    variant = COMMAND_CATALOG_V0_1.resolve(
        CommandId.SYSTEM_VERSION,
        PlatformFamily.IOS_XE,
    )
    assert definition.normalized_model is NormalizedModelId.DEVICE_INFO
    assert definition.requirement is CommandRequirement.REQUIRED
    assert definition.unsupported_platform_policy is UnsupportedPlatformPolicy.SKIP
    assert variant is not None
    assert variant.cli_command == "show version"
    assert variant.parser_id is ParserId.IOS_SHOW_VERSION_V1


def test_show_inventory_contract_is_productive() -> None:
    definition = COMMAND_CATALOG_V0_1.get(CommandId.SYSTEM_INVENTORY)
    variant = COMMAND_CATALOG_V0_1.resolve(
        CommandId.SYSTEM_INVENTORY,
        PlatformFamily.IOS_XE,
    )
    assert definition.normalized_model is NormalizedModelId.HARDWARE_INVENTORY
    assert definition.requirement is CommandRequirement.REQUIRED
    assert variant is not None
    assert variant.cli_command == "show inventory"
    assert variant.parser_id is ParserId.IOS_SHOW_INVENTORY_V1


def test_vlan_observation_contract_is_stable() -> None:
    assert CommandId.VLANS_BRIEF.value == "vlans.brief"
    assert ParserId.IOS_SHOW_VLAN_BRIEF_V1.value == "ios.show_vlan_brief.v1"
    assert NormalizedModelId.VLAN_OBSERVATION.value == "VlanObservation"
    assert "VLAN_INFO" not in NormalizedModelId.__members__

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


def test_vlan_observation_rejects_unsupported_platforms() -> None:
    assert COMMAND_CATALOG_V0_1.resolve(CommandId.VLANS_BRIEF, PlatformFamily.NX_OS) is None
    assert COMMAND_CATALOG_V0_1.resolve(CommandId.VLANS_BRIEF, PlatformFamily.UNKNOWN) is None


def test_vlan_catalog_scope_is_closed_and_read_only() -> None:
    vlan_definitions = tuple(
        definition
        for definition in COMMAND_CATALOG_V0_1.commands
        if definition.category is CommandCategory.VLANS
    )

    assert tuple(definition.command_id for definition in vlan_definitions) == (
        CommandId.VLANS_BRIEF,
    )
    for definition in vlan_definitions:
        assert definition.read_only is True
        for variant in definition.variants.values():
            assert variant.cli_command == "show vlan brief"


def test_all_mvp_cli_commands_are_read_only_show_commands() -> None:
    for definition in COMMAND_CATALOG_V0_1.commands:
        assert definition.read_only is True
        for variant in definition.variants.values():
            assert variant.cli_command.lower().startswith("show ")


def test_running_config_is_marked_sensitive() -> None:
    definition = COMMAND_CATALOG_V0_1.get(CommandId.CONFIG_RUNNING)
    assert definition.sensitive_output is True


def test_catalog_serializes_platform_keys_and_enum_values() -> None:
    payload = COMMAND_CATALOG_V0_1.model_dump(mode="json")
    show_version = next(
        item for item in payload["commands"] if item["command_id"] == "system.version"
    )
    assert show_version["variants"]["ios"]["cli_command"] == "show version"
    assert show_version["variants"]["ios_xe"]["parser_id"] == "ios.show_version.v1"
