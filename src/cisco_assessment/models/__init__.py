"""Public data-model API for the MVP."""

from .assessment import AssessmentRun
from .device import Device, DeviceSnapshot
from .enums import AssessmentRunStatus, CommandExecutionStatus, PlatformFamily
from .execution import CommandExecution
from .normalized import (
    HARDWARE_INVENTORY_SCHEMA_VERSION,
    DeviceInfo,
    HardwareComponent,
    HardwareComponentKind,
    HardwareComponentType,
    HardwareInventory,
    HardwareInventoryRecord,
    hardware_inventory_record_id,
)
from .raw import RawCommandOutput

__all__ = [
    "HARDWARE_INVENTORY_SCHEMA_VERSION",
    "AssessmentRun",
    "AssessmentRunStatus",
    "CommandExecution",
    "CommandExecutionStatus",
    "Device",
    "DeviceInfo",
    "DeviceSnapshot",
    "HardwareComponent",
    "HardwareComponentKind",
    "HardwareComponentType",
    "HardwareInventory",
    "HardwareInventoryRecord",
    "PlatformFamily",
    "RawCommandOutput",
    "hardware_inventory_record_id",
]
