"""Deterministic HardwareInventory assessment rules over canonical v0.2 records."""

from __future__ import annotations

from collections import Counter

from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import HardwareComponentType, HardwareInventory

from .catalog import RuleCatalog
from .context import AssessmentContext
from .enums import AssessmentStatus, FindingSeverity, RuleCategory
from .evidence import EvidenceRequest
from .models import RuleDecision, RuleMetadata

_IOS_PLATFORMS = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})


def _record_field_path(index: int, field: str) -> str:
    return f"records[{index}].{field}"


def _component_type_evidence(model: HardwareInventory) -> tuple[EvidenceRequest, ...]:
    return tuple(
        EvidenceRequest(
            field_path=_record_field_path(index, "component_type"),
            observed_value=record.component_type.value,
        )
        for index, record in enumerate(model.records)
    )


class ChassisIdentityObservedRule:
    """Require PID and serial identity for every observed chassis member."""

    _metadata = RuleMetadata(
        rule_id="HW-001",
        version="0.1.0",
        title="Chassis identity observed",
        description=(
            "Checks that every chassis/member record reports a PID and serial number."
        ),
        category=RuleCategory.SYSTEM,
        severity=FindingSeverity.MEDIUM,
        normalized_model="HardwareInventory",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("records",),
        evidence_fields=("records",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Verify platform inventory visibility and investigate missing chassis identity fields."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: HardwareInventory, context: AssessmentContext) -> RuleDecision:
        del context
        members = tuple(
            (index, record)
            for index, record in enumerate(model.records)
            if record.component_type is HardwareComponentType.CHASSIS_MEMBER
        )
        if not members:
            return RuleDecision(
                status=AssessmentStatus.ERROR,
                message="No chassis_member record was observed in hardware inventory.",
                evidence=_component_type_evidence(model),
            )

        evidence: list[EvidenceRequest] = []
        incomplete: list[str] = []
        for index, record in members:
            evidence.extend(
                (
                    EvidenceRequest(
                        field_path=_record_field_path(index, "component_type"),
                        observed_value=record.component_type.value,
                    ),
                    EvidenceRequest(
                        field_path=_record_field_path(index, "pid"),
                        observed_value=record.pid,
                    ),
                    EvidenceRequest(
                        field_path=_record_field_path(index, "serial_number"),
                        observed_value=record.serial_number,
                    ),
                )
            )
            missing = tuple(
                label
                for label, value in (
                    ("PID", record.pid),
                    ("serial number", record.serial_number),
                )
                if value is None
            )
            if missing:
                incomplete.append(f"{record.id} ({record.name}): {', '.join(missing)}")

        return RuleDecision(
            status=AssessmentStatus.WARNING if incomplete else AssessmentStatus.PASS,
            message=(
                "Chassis identity is complete for all "
                f"{len(members)} observed chassis member(s)."
                if not incomplete
                else "Chassis member identity is incomplete: " + "; ".join(incomplete) + "."
            ),
            evidence=tuple(evidence),
        )


class UniqueInventorySerialsRule:
    """Detect duplicate populated serial numbers across all physical records."""

    _metadata = RuleMetadata(
        rule_id="HW-002",
        version="0.1.0",
        title="Unique hardware serial numbers",
        description=(
            "Checks that populated serial numbers are not duplicated across inventory records."
        ),
        category=RuleCategory.SYSTEM,
        severity=FindingSeverity.LOW,
        normalized_model="HardwareInventory",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("records",),
        evidence_fields=("records",),
        missing_data_status=AssessmentStatus.INFO,
        recommendation="Review duplicated inventory records and confirm physical asset identity.",
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: HardwareInventory, context: AssessmentContext) -> RuleDecision:
        del context
        populated = tuple(
            (index, record.serial_number)
            for index, record in enumerate(model.records)
            if record.serial_number is not None
        )
        counts = Counter(serial for _, serial in populated)
        duplicates = tuple(sorted(serial for serial, count in counts.items() if count > 1))
        return RuleDecision(
            status=AssessmentStatus.WARNING if duplicates else AssessmentStatus.PASS,
            message=(
                "Duplicate hardware serial numbers observed: " + ", ".join(duplicates) + "."
                if duplicates
                else "No duplicate populated hardware serial numbers were observed."
            ),
            evidence=tuple(
                EvidenceRequest(
                    field_path=_record_field_path(index, "serial_number"),
                    observed_value=serial,
                )
                for index, serial in populated
            ),
        )


class HardwareInventoryObservedRule:
    """Record the number of canonical physical inventory records."""

    _metadata = RuleMetadata(
        rule_id="HW-003",
        version="0.1.0",
        title="Hardware inventory observed",
        description="Records the normalized physical inventory record count.",
        category=RuleCategory.SYSTEM,
        severity=FindingSeverity.INFO,
        normalized_model="HardwareInventory",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("records",),
        evidence_fields=("records",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Use the normalized inventory as the baseline for asset and lifecycle review.",
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: HardwareInventory, context: AssessmentContext) -> RuleDecision:
        del context
        count = len(model.records)
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=f"Normalized hardware inventory contains {count} physical record(s).",
            evidence=_component_type_evidence(model),
        )


HARDWARE_INVENTORY_RULES = (
    ChassisIdentityObservedRule(),
    UniqueInventorySerialsRule(),
    HardwareInventoryObservedRule(),
)


def hardware_inventory_rule_catalog() -> RuleCatalog[HardwareInventory]:
    """Return the immutable HardwareInventory v0.2 rule catalog."""

    return RuleCatalog[HardwareInventory](HARDWARE_INVENTORY_RULES)
