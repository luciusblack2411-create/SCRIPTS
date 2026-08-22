from uuid import uuid4

from cisco_assessment.assessment import (
    AssessmentContext,
    AssessmentEngine,
    AssessmentStatus,
    hardware_inventory_rule_catalog,
)
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import (
    HardwareComponent,
    HardwareComponentKind,
    HardwareInventory,
)


def _context() -> AssessmentContext:
    return AssessmentContext(
        assessment_run_id=uuid4(),
        device_id=uuid4(),
        platform=PlatformFamily.IOS_XE,
    )


def _component(name: str, serial: str | None, kind: HardwareComponentKind) -> HardwareComponent:
    return HardwareComponent(
        name=name,
        description=name,
        pid="C9300-48P" if kind is HardwareComponentKind.CHASSIS else "PART-1",
        vid="V01",
        serial_number=serial,
        kind=kind,
    )


def test_hardware_inventory_rules_cover_pass_warning_and_info() -> None:
    chassis = _component("Chassis", "FOC0000AAAA", HardwareComponentKind.CHASSIS)
    duplicate = _component("Module", "FOC0000AAAA", HardwareComponentKind.MODULE)
    model = HardwareInventory(
        platform=PlatformFamily.IOS_XE,
        chassis=chassis,
        modules=(duplicate,),
    )

    result = AssessmentEngine(hardware_inventory_rule_catalog()).evaluate(model, _context())
    statuses = {outcome.rule_id: outcome.status for outcome in result.outcomes}

    assert statuses["HW-001"] is AssessmentStatus.PASS
    assert statuses["HW-002"] is AssessmentStatus.WARNING
    assert statuses["HW-003"] is AssessmentStatus.INFO
    assert {finding.rule_id for finding in result.findings} == {"HW-002", "HW-003"}


def test_chassis_identity_rule_warns_when_serial_is_missing() -> None:
    chassis = HardwareComponent(
        name="Chassis",
        description="Cisco chassis",
        pid="C9300-48P",
        serial_number=None,
        kind=HardwareComponentKind.CHASSIS,
    )
    result = AssessmentEngine(hardware_inventory_rule_catalog()).evaluate(
        HardwareInventory(platform=PlatformFamily.IOS_XE, chassis=chassis),
        _context(),
    )
    outcome = next(item for item in result.outcomes if item.rule_id == "HW-001")
    assert outcome.status is AssessmentStatus.WARNING
