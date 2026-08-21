"""Initial IOS/IOS-XE command catalog for the MVP."""

from cisco_assessment.models.enums import PlatformFamily

from .enums import (
    CommandCategory,
    CommandId,
    CommandRequirement,
    NormalizedModelId,
    ParserId,
)
from .models import CommandCatalog, CommandDefinition, CommandVariant


def _ios_variants(cli_command: str, parser_id: ParserId) -> dict[PlatformFamily, CommandVariant]:
    variant = CommandVariant(cli_command=cli_command, parser_id=parser_id)
    return {
        PlatformFamily.IOS: variant,
        PlatformFamily.IOS_XE: variant.model_copy(deep=True),
    }


def _command(
    command_id: CommandId,
    category: CommandCategory,
    purpose: str,
    normalized_model: NormalizedModelId,
    requirement: CommandRequirement,
    cli_command: str,
    parser_id: ParserId,
    *,
    sensitive_output: bool = False,
) -> CommandDefinition:
    return CommandDefinition(
        command_id=command_id,
        category=category,
        purpose=purpose,
        normalized_model=normalized_model,
        requirement=requirement,
        variants=_ios_variants(cli_command, parser_id),
        sensitive_output=sensitive_output,
    )


COMMAND_CATALOG_V0_1 = CommandCatalog(
    commands=(
        _command(
            CommandId.SYSTEM_VERSION,
            CommandCategory.SYSTEM,
            "Collect device identity, software version, hardware platform, and uptime.",
            NormalizedModelId.DEVICE_INFO,
            CommandRequirement.REQUIRED,
            "show version",
            ParserId.IOS_SHOW_VERSION_V1,
        ),
        _command(
            CommandId.SYSTEM_INVENTORY,
            CommandCategory.SYSTEM,
            "Collect chassis, module, serial-number, and field-replaceable inventory data.",
            NormalizedModelId.INVENTORY_ITEM,
            CommandRequirement.REQUIRED,
            "show inventory",
            ParserId.IOS_SHOW_INVENTORY_V1,
        ),
        _command(
            CommandId.SYSTEM_CLOCK,
            CommandCategory.SYSTEM,
            "Collect device clock and timezone information.",
            NormalizedModelId.DEVICE_CLOCK,
            CommandRequirement.REQUIRED,
            "show clock detail",
            ParserId.IOS_SHOW_CLOCK_DETAIL_V1,
        ),
        _command(
            CommandId.SYSTEM_STACK,
            CommandCategory.SYSTEM,
            "Collect switch stack membership and role information when supported.",
            NormalizedModelId.STACK_INFO,
            CommandRequirement.OPTIONAL,
            "show switch detail",
            ParserId.IOS_SHOW_SWITCH_DETAIL_V1,
        ),
        _command(
            CommandId.SYSTEM_REDUNDANCY,
            CommandCategory.SYSTEM,
            "Collect supervisor and control-plane redundancy state when supported.",
            NormalizedModelId.REDUNDANCY_INFO,
            CommandRequirement.OPTIONAL,
            "show redundancy",
            ParserId.IOS_SHOW_REDUNDANCY_V1,
        ),
        _command(
            CommandId.INTERFACES_DETAIL,
            CommandCategory.INTERFACES,
            "Collect detailed interface operational state and counters.",
            NormalizedModelId.INTERFACE_OBSERVATION,
            CommandRequirement.REQUIRED,
            "show interfaces",
            ParserId.IOS_SHOW_INTERFACES_V1,
        ),
        _command(
            CommandId.INTERFACES_STATUS,
            CommandCategory.INTERFACES,
            "Collect concise switchport status, VLAN, duplex, and speed observations.",
            NormalizedModelId.INTERFACE_OBSERVATION,
            CommandRequirement.REQUIRED,
            "show interfaces status",
            ParserId.IOS_SHOW_INTERFACES_STATUS_V1,
        ),
        _command(
            CommandId.INTERFACES_IP_BRIEF,
            CommandCategory.INTERFACES,
            "Collect interface addressing and administrative/operational status observations.",
            NormalizedModelId.INTERFACE_OBSERVATION,
            CommandRequirement.REQUIRED,
            "show ip interface brief",
            ParserId.IOS_SHOW_IP_INTERFACE_BRIEF_V1,
        ),
        _command(
            CommandId.VLANS_BRIEF,
            CommandCategory.VLANS,
            "Collect configured VLAN identifiers, names, states, and access-port membership.",
            NormalizedModelId.VLAN_INFO,
            CommandRequirement.REQUIRED,
            "show vlan brief",
            ParserId.IOS_SHOW_VLAN_BRIEF_V1,
        ),
        _command(
            CommandId.STP_SUMMARY,
            CommandCategory.SPANNING_TREE,
            "Collect global spanning-tree mode and summary state.",
            NormalizedModelId.SPANNING_TREE_SUMMARY,
            CommandRequirement.REQUIRED,
            "show spanning-tree summary",
            ParserId.IOS_SHOW_SPANNING_TREE_SUMMARY_V1,
        ),
        _command(
            CommandId.STP_DETAIL,
            CommandCategory.SPANNING_TREE,
            "Collect per-instance spanning-tree topology and port-role observations.",
            NormalizedModelId.SPANNING_TREE_INSTANCE,
            CommandRequirement.REQUIRED,
            "show spanning-tree",
            ParserId.IOS_SHOW_SPANNING_TREE_V1,
        ),
        _command(
            CommandId.ETHERCHANNEL_SUMMARY,
            CommandCategory.ETHERCHANNEL,
            "Collect EtherChannel groups, member ports, protocols, and bundle state.",
            NormalizedModelId.ETHERCHANNEL_INFO,
            CommandRequirement.REQUIRED,
            "show etherchannel summary",
            ParserId.IOS_SHOW_ETHERCHANNEL_SUMMARY_V1,
        ),
        _command(
            CommandId.NEIGHBORS_CDP_DETAIL,
            CommandCategory.NEIGHBORS,
            "Collect detailed Cisco Discovery Protocol neighbor observations when enabled.",
            NormalizedModelId.NEIGHBOR_OBSERVATION,
            CommandRequirement.OPTIONAL,
            "show cdp neighbors detail",
            ParserId.IOS_SHOW_CDP_NEIGHBORS_DETAIL_V1,
        ),
        _command(
            CommandId.NEIGHBORS_LLDP_DETAIL,
            CommandCategory.NEIGHBORS,
            "Collect detailed LLDP neighbor observations when enabled.",
            NormalizedModelId.NEIGHBOR_OBSERVATION,
            CommandRequirement.OPTIONAL,
            "show lldp neighbors detail",
            ParserId.IOS_SHOW_LLDP_NEIGHBORS_DETAIL_V1,
        ),
        _command(
            CommandId.RESOURCES_CPU,
            CommandCategory.RESOURCES,
            "Collect CPU utilization and process-level CPU observations.",
            NormalizedModelId.CPU_METRICS,
            CommandRequirement.REQUIRED,
            "show processes cpu sorted",
            ParserId.IOS_SHOW_PROCESSES_CPU_V1,
        ),
        _command(
            CommandId.RESOURCES_MEMORY,
            CommandCategory.RESOURCES,
            "Collect memory utilization and process-level memory observations.",
            NormalizedModelId.MEMORY_METRICS,
            CommandRequirement.REQUIRED,
            "show processes memory sorted",
            ParserId.IOS_SHOW_PROCESSES_MEMORY_V1,
        ),
        _command(
            CommandId.ENVIRONMENT_HEALTH,
            CommandCategory.ENVIRONMENT,
            "Collect environmental sensors, fans, power supplies, and temperature health when supported.",
            NormalizedModelId.ENVIRONMENT_HEALTH,
            CommandRequirement.OPTIONAL,
            "show environment all",
            ParserId.IOS_SHOW_ENVIRONMENT_V1,
        ),
        _command(
            CommandId.LOGGING_BUFFER,
            CommandCategory.LOGGING,
            "Collect logging configuration and current buffered log observations.",
            NormalizedModelId.LOGGING_SUMMARY,
            CommandRequirement.REQUIRED,
            "show logging",
            ParserId.IOS_SHOW_LOGGING_V1,
        ),
        _command(
            CommandId.CONFIG_RUNNING,
            CommandCategory.CONFIGURATION,
            "Collect the active running configuration for read-only assessment inputs.",
            NormalizedModelId.RUNNING_CONFIG,
            CommandRequirement.REQUIRED,
            "show running-config",
            ParserId.IOS_SHOW_RUNNING_CONFIG_V1,
            sensitive_output=True,
        ),
        _command(
            CommandId.TIME_NTP_STATUS,
            CommandCategory.TIME,
            "Collect NTP synchronization status when NTP is available.",
            NormalizedModelId.NTP_STATUS,
            CommandRequirement.OPTIONAL,
            "show ntp status",
            ParserId.IOS_SHOW_NTP_STATUS_V1,
        ),
    )
)
