"""Deterministic HardwareInventory assessment rules v0.1."""

from __future__ import annotations

from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import HardwareInventory

from .catalog import RuleCatalog
from .context import AssessmentContext
from .enums import AssessmentStatus, FindingSeverity, RuleCategory
from .evidence import EvidenceRequest
from .models import RuleDecision, RuleMetadata

_IOS_PLATFORMS = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})


class ChassisIdentityObservedRule:
    """Require a chassis PID and serial number in physical inventory."""

    _metadata = RuleMetadata(
        rule_id="HW-001",
        version="0.1.0",
        title="Chassis identity observed",
        description="Checks that show inventory reports a chassis PID and serial number.",
        category=RuleCategory.SYSTEM,
        severity=FindingSeverity.MEDIUM,
        normalized_model="HardwareInventory",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("chassis",),
        evidence_fields=("chassis", "chassis.pid", "chassis.serial_number"),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Verify platform inventory visibility and investigate missing chassis identity fields.",
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: HardwareInventory, context: AssessmentContext) -> RuleDecision:
        del context
        assert model.chassis is not None
        missing = [
            field
            for field, value in (
                ("PID", model.chassis.pid),
                ("serial number", model.chassis.serial_number),
            )
            if value is None
        ]
        status = AssessmentStatus.WARNING if missing else AssessmentStatus.PASS
        message = (
            "Chassis identity is complete in show inventory."
            if not missing
            else "Chassis inventory is missing " + " and ".join(missing) + "."
        )
        return RuleDecision(
            status=status,
            message=message,
            evidence=(
                EvidenceRequest(field_path="chassis.pid", observed_value=model.chassis.pid),
                EvidenceRequest(
                    field_path="chassis.serial_number",
                    observed_value=model.chassis.serial_number,
                ),
            ),
        )


class UniqueInventorySerialsRule:
    """Detect duplicate non-empty serial numbers in one inventory snapshot."""

    _metadata = RuleMetadata(
        rule_id="HW-002",
        version="0.1.0",
        title="Unique hardware serial numbers",
        description="Checks that populated serial numbers are not duplicated across inventory records.",
        category=RuleCategory.SYSTEM,
        severity=FindingSeverity.LOW,
        normalized_model="HardwareInventory",
        supported_platforms=_IOS_PLATFORMS,
        evidence_fields=("components", "modules", "chassis.serial_number"),
        missing_data_status=AssessmentStatus.INFO,
        recommendation="Review duplicated inventory records and confirm physical asset identity.",
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: HardwareInventory, context: AssessmentContext) -> RuleDecision:
        del context
        serials = [
            item.serial_number
            for item in model.all_components
            if item.serial_number is not None
        ]
        duplicates = sorted({serial for serial in serials if serials.count(serial) > 1})
        return RuleDecision(
            status=AssessmentStatus.WARNING if duplicates else AssessmentStatus.PASS,
            message=(
                "Duplicate hardware serial numbers observed: " + ", ".join(duplicates) + "."
                if duplicates
                else "No duplicate populated hardware serial numbers were observed."
            ),
            evidence=(
                EvidenceRequest(
                    field_path="components",
                    observed_value=[item.model_dump(mode="json") for item in model.components],
                ),
                EvidenceRequest(
                    field_path="modules",
                    observed_value=[item.model_dump(mode="json") for item in model.modules],
                ),
            ),
        )


class HardwareInventoryObservedRule:
    """Record the number of physical inventory records for downstream review."""

    _metadata = RuleMetadata(
        rule_id="HW-003",
        version="0.1.0",
        title="Hardware inventory observed",
        description="Records the normalized physical inventory record count.",
        category=RuleCategory.SYSTEM,
        severity=FindingSeverity.INFO,
        normalized_model="HardwareInventory",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("chassis",),
        evidence_fields=("chassis", "modules", "components"),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Use the normalized inventory as the baseline for asset and lifecycle review.",
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: HardwareInventory, context: AssessmentContext) -> RuleDecision:
        del context
        count = len(model.all_components)
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=f"Normalized hardware inventory contains {count} physical record(s).",
            evidence=(
                EvidenceRequest(
                    field_path="chassis",
                    observed_value=None if model.chassis is None else model.chassis.model_dump(mode="json"),
                ),
                EvidenceRequest(
                    field_path="modules",
                    observed_value=[item.model_dump(mode="json") for item in model.modules],
                ),
                EvidenceRequest(
                    field_path="components",
                    observed_value=[item.model_dump(mode="json") for item in model.components],
                ),
            ),
        )


HARDWARE_INVENTORY_RULES = (
    ChassisIdentityObservedRule(),
    UniqueInventorySerialsRule(),
    HardwareInventoryObservedRule(),
)


def hardware_inventory_rule_catalog() -> RuleCatalog[HardwareInventory]:
    """Return the immutable HardwareInventory v0.1 rule catalog."""

    return RuleCatalog[HardwareInventory](HARDWARE_INVENTORY_RULES)
