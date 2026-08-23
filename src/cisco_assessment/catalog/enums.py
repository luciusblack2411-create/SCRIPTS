"""Typed identifiers and enums for the command catalog v0.1."""

from enum import StrEnum


class CommandId(StrEnum):
    SYSTEM_VERSION = "system.version"
    SYSTEM_INVENTORY = "system.inventory"
    SYSTEM_CLOCK = "system.clock"
    SYSTEM_STACK = "system.stack"
    SYSTEM_REDUNDANCY = "system.redundancy"
    INTERFACES_DETAIL = "interfaces.detail"
    INTERFACES_STATUS = "interfaces.status"
    INTERFACES_IP_BRIEF = "interfaces.ip_brief"
    VLANS_BRIEF = "vlans.brief"
    STP_SUMMARY = "stp.summary"
    STP_DETAIL = "stp.detail"
    ETHERCHANNEL_SUMMARY = "etherchannel.summary"
    NEIGHBORS_CDP_DETAIL = "neighbors.cdp_detail"
    NEIGHBORS_LLDP_DETAIL = "neighbors.lldp_detail"
    RESOURCES_CPU = "resources.cpu"
    RESOURCES_MEMORY = "resources.memory"
    ENVIRONMENT_HEALTH = "environment.health"
    LOGGING_BUFFER = "logging.buffer"
    CONFIG_RUNNING = "config.running"
    TIME_NTP_STATUS = "time.ntp_status"


class CommandCategory(StrEnum):
    SYSTEM = "system"
    INTERFACES = "interfaces"
    VLANS = "vlans"
    SPANNING_TREE = "spanning_tree"
    ETHERCHANNEL = "etherchannel"
    NEIGHBORS = "neighbors"
    RESOURCES = "resources"
    ENVIRONMENT = "environment"
    LOGGING = "logging"
    CONFIGURATION = "configuration"
    TIME = "time"


class CommandRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class UnsupportedPlatformPolicy(StrEnum):
    SKIP = "skip"


class ParserId(StrEnum):
    IOS_SHOW_VERSION_V1 = "ios.show_version.v1"
    IOS_SHOW_INVENTORY_V1 = "ios.show_inventory.v1"
    IOS_SHOW_CLOCK_DETAIL_V1 = "ios.show_clock_detail.v1"
    IOS_SHOW_SWITCH_DETAIL_V1 = "ios.show_switch_detail.v1"
    IOS_SHOW_REDUNDANCY_V1 = "ios.show_redundancy.v1"
    IOS_SHOW_INTERFACES_V1 = "ios.show_interfaces.v1"
    IOS_SHOW_INTERFACES_STATUS_V1 = "ios.show_interfaces_status.v1"
    IOS_SHOW_IP_INTERFACE_BRIEF_V1 = "ios.show_ip_interface_brief.v1"
    IOS_SHOW_VLAN_BRIEF_V1 = "ios.show_vlan_brief.v1"
    IOS_SHOW_SPANNING_TREE_SUMMARY_V1 = "ios.show_spanning_tree_summary.v1"
    IOS_SHOW_SPANNING_TREE_V1 = "ios.show_spanning_tree.v1"
    IOS_SHOW_ETHERCHANNEL_SUMMARY_V1 = "ios.show_etherchannel_summary.v1"
    IOS_SHOW_CDP_NEIGHBORS_DETAIL_V1 = "ios.show_cdp_neighbors_detail.v1"
    IOS_SHOW_LLDP_NEIGHBORS_DETAIL_V1 = "ios.show_lldp_neighbors_detail.v1"
    IOS_SHOW_PROCESSES_CPU_V1 = "ios.show_processes_cpu.v1"
    IOS_SHOW_PROCESSES_MEMORY_V1 = "ios.show_processes_memory.v1"
    IOS_SHOW_ENVIRONMENT_V1 = "ios.show_environment.v1"
    IOS_SHOW_LOGGING_V1 = "ios.show_logging.v1"
    IOS_SHOW_RUNNING_CONFIG_V1 = "ios.show_running_config.v1"
    IOS_SHOW_NTP_STATUS_V1 = "ios.show_ntp_status.v1"


class NormalizedModelId(StrEnum):
    DEVICE_INFO = "DeviceInfo"
    HARDWARE_INVENTORY = "HardwareInventory"
    INVENTORY_ITEM = "InventoryItem"
    DEVICE_CLOCK = "DeviceClock"
    STACK_INFO = "StackInfo"
    REDUNDANCY_INFO = "RedundancyInfo"
    INTERFACE_OBSERVATION = "InterfaceObservation"
    VLAN_OBSERVATION = "VlanObservation"
    VLAN_INFO = "VlanInfo"
    SPANNING_TREE_SUMMARY = "SpanningTreeSummary"
    SPANNING_TREE_INSTANCE = "SpanningTreeInstance"
    ETHERCHANNEL_INFO = "EtherChannelInfo"
    NEIGHBOR_OBSERVATION = "NeighborObservation"
    CPU_METRICS = "CpuMetrics"
    MEMORY_METRICS = "MemoryMetrics"
    ENVIRONMENT_HEALTH = "EnvironmentHealth"
    LOGGING_SUMMARY = "LoggingSummary"
    RUNNING_CONFIG = "RunningConfig"
    NTP_STATUS = "NtpStatus"
