"""Public data-model API for the MVP."""

from .assessment import AssessmentRun
from .device import Device, DeviceSnapshot
from .enums import AssessmentRunStatus, CommandExecutionStatus, PlatformFamily
from .execution import CommandExecution
from .interface import (
    INTERFACE_OBSERVATION_SCHEMA_VERSION,
    InterfaceObservation,
    InterfaceStatusRecord,
)
from .normalized import (
    HARDWARE_INVENTORY_SCHEMA_VERSION,
    DeviceInfo,
    HardwareComponentType,
    HardwareInventory,
    HardwareInventoryRecord,
    hardware_inventory_record_id,
)
from .raw import RawCommandOutput
from .switchport import (
    SWITCHPORT_OBSERVATION_SCHEMA_VERSION,
    SwitchportObservation,
    SwitchportRecord,
)
from .vlan import (
    VLAN_OBSERVATION_SCHEMA_VERSION,
    VlanObservation,
    VlanRecord,
    VlanStatus,
)

__all__ = [
    "HARDWARE_INVENTORY_SCHEMA_VERSION",
    "INTERFACE_OBSERVATION_SCHEMA_VERSION",
    "SWITCHPORT_OBSERVATION_SCHEMA_VERSION",
    "VLAN_OBSERVATION_SCHEMA_VERSION",
    "AssessmentRun",
    "AssessmentRunStatus",
    "CommandExecution",
    "CommandExecutionStatus",
    "Device",
    "DeviceInfo",
    "DeviceSnapshot",
    "HardwareComponentType",
    "HardwareInventory",
    "HardwareInventoryRecord",
    "InterfaceObservation",
    "InterfaceStatusRecord",
    "PlatformFamily",
    "RawCommandOutput",
    "SwitchportObservation",
    "SwitchportRecord",
    "VlanObservation",
    "VlanRecord",
    "VlanStatus",
    "hardware_inventory_record_id",
]
