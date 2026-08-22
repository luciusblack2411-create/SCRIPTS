from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from cisco_assessment.assessment import (
    AssessmentContext,
    AssessmentEngine,
    AssessmentStatus,
    ChassisIdentityObservedRule,
    NormalizedFieldSource,
    RuleCatalog,
    SourceTrace,
    UniqueInventorySerialsRule,
    hardware_inventory_rule_catalog,
)
from cisco_assessment.catalog.enums import CommandId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import (
    HardwareComponentType,
    HardwareInventory,
    HardwareInventoryRecord,
)
from cisco_assessment.parsers import IOSShowInventoryParser

FIXTURES = Path(__file__).parents[2] / "fixtures" / "ios" / "show_inventory"


def _context(*, source_evidence: tuple[NormalizedFieldSource, ...] = ()) -> AssessmentContext:
    run_id = source_evidence[0].source.assessment_run_id if source_evidence else uuid4()
    return AssessmentContext(
        assessment_run_id=run_id,
        device_id=uuid4(),
        platform=PlatformFamily.IOS_XE,
        source_evidence=source_evidence,
    )


def _record(
    ordinal: int,
    *,
    name: str,
    component_type: HardwareComponentType,
    pid: str | None = "PID-1",
    serial_number: str | None = None,
) -> HardwareInventoryRecord:
    return HardwareInventoryRecord(
        ordinal=ordinal,
        name=name,
        description=name,
        pid=pid,
        vid="V01",
        serial_number=serial_number,
        component_type=component_type,
    )


def _inventory(*records: HardwareInventoryRecord) -> HardwareInventory:
    return HardwareInventory(platform=PlatformFamily.IOS_XE, records=records)


def _outcome(rule: object, model: BaseModel, context: AssessmentContext | None = None):
    result = AssessmentEngine(RuleCatalog([rule])).evaluate(model, context or _context())
    return result.outcomes[0]


def _real_17_inventory() -> tuple[HardwareInventory, AssessmentContext]:
    execution = CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.SYSTEM_INVENTORY.value,
        command="show inventory",
        sequence=2,
    )
    content = (FIXTURES / "c9300_iosxe_pager_backspace.txt").read_text(encoding="utf-8")
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)
    parsed = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )
    source_evidence = tuple(
        NormalizedFieldSource(
            normalized_model="HardwareInventory",
            field_path=item.field,
            source=SourceTrace(
                assessment_run_id=parsed.trace.assessment_run_id,
                command_execution_id=parsed.trace.command_execution_id,
                raw_output_id=parsed.trace.raw_output_id,
                raw_sha256=parsed.trace.raw_sha256,
                parser_id=parsed.trace.parser_id.value,
                parser_version=parsed.trace.parser_version,
                platform=parsed.trace.platform,
                extractor=item.extractor,
                line_start=item.line_start,
                line_end=item.line_end,
            ),
        )
        for item in parsed.evidence
    )
    return parsed.data, _context(source_evidence=source_evidence)


def test_catalog_keeps_stable_ids_and_declares_only_canonical_records() -> None:
    catalog = hardware_inventory_rule_catalog()

    assert tuple(rule.metadata.rule_id for rule in catalog.rules) == (
        "HW-001",
        "HW-002",
        "HW-003",
    )
    for rule in catalog.rules:
        assert rule.metadata.required_fields == ("records",)
        assert rule.metadata.evidence_fields == ("records",)


def test_hw_001_evaluates_every_chassis_member_with_canonical_evidence() -> None:
    model = _inventory(
        _record(
            1,
            name="Switch 1",
            component_type=HardwareComponentType.CHASSIS_MEMBER,
            pid="C9300-48P",
            serial_number="FOC0000AAAA",
        ),
        _record(
            2,
            name="Power Supply Module 1",
            component_type=HardwareComponentType.POWER_SUPPLY,
            serial_number="PWR0001",
        ),
        _record(
            3,
            name="Switch 2",
            component_type=HardwareComponentType.CHASSIS_MEMBER,
            pid="C9300-48P",
            serial_number="FOC0000BBBB",
        ),
    )

    outcome = _outcome(ChassisIdentityObservedRule(), model)

    assert outcome.status is AssessmentStatus.PASS
    assert tuple(item.field_path for item in outcome.evidence) == (
        "records[0].component_type",
        "records[0].pid",
        "records[0].serial_number",
        "records[2].component_type",
        "records[2].pid",
        "records[2].serial_number",
    )


def test_hw_001_warns_when_any_chassis_member_identity_is_incomplete() -> None:
    model = _inventory(
        _record(
            1,
            name="Switch 1",
            component_type=HardwareComponentType.CHASSIS_MEMBER,
            pid="C9300-48P",
            serial_number="FOC0000AAAA",
        ),
        _record(
            2,
            name="Switch 2",
            component_type=HardwareComponentType.CHASSIS_MEMBER,
            pid=None,
            serial_number=None,
        ),
    )

    outcome = _outcome(ChassisIdentityObservedRule(), model)

    assert outcome.status is AssessmentStatus.WARNING
    assert "hw:0002 (Switch 2): PID, serial number" in outcome.message
    missing = {item.field_path: item.observed_value for item in outcome.evidence}
    assert missing["records[1].pid"] is None
    assert missing["records[1].serial_number"] is None


def test_hw_002_checks_populated_serials_across_all_records() -> None:
    duplicate_model = _inventory(
        _record(
            1,
            name="Switch 1",
            component_type=HardwareComponentType.CHASSIS_MEMBER,
            serial_number="DUPLICATE",
        ),
        _record(
            2,
            name="Gi1/1/1",
            component_type=HardwareComponentType.TRANSCEIVER,
            serial_number="UNIQUE",
        ),
        _record(
            3,
            name="Power Supply Module 1",
            component_type=HardwareComponentType.POWER_SUPPLY,
            serial_number="DUPLICATE",
        ),
    )
    duplicate = _outcome(UniqueInventorySerialsRule(), duplicate_model)
    assert duplicate.status is AssessmentStatus.WARNING
    assert "DUPLICATE" in duplicate.message
    assert tuple(item.field_path for item in duplicate.evidence) == (
        "records[0].serial_number",
        "records[1].serial_number",
        "records[2].serial_number",
    )

    unique_model = _inventory(
        _record(
            1,
            name="Switch 1",
            component_type=HardwareComponentType.CHASSIS_MEMBER,
            serial_number="SERIAL-1",
        ),
        _record(
            2,
            name="Gi1/1/1",
            component_type=HardwareComponentType.TRANSCEIVER,
            serial_number="SERIAL-2",
        ),
        _record(
            3,
            name="Unknown",
            component_type=HardwareComponentType.OTHER,
            serial_number=None,
        ),
    )
    assert _outcome(UniqueInventorySerialsRule(), unique_model).status is AssessmentStatus.PASS


def test_real_17_records_use_only_records_paths_and_preserve_raw_traceability() -> None:
    model, context = _real_17_inventory()
    result = AssessmentEngine(hardware_inventory_rule_catalog()).evaluate(model, context)
    outcomes = {item.rule_id: item for item in result.outcomes}

    assert len(model.records) == 17
    assert outcomes["HW-001"].status is AssessmentStatus.PASS
    assert outcomes["HW-002"].status is AssessmentStatus.PASS
    assert outcomes["HW-003"].status is AssessmentStatus.INFO
    assert "17 physical record(s)" in outcomes["HW-003"].message

    hw_001_paths = tuple(item.field_path for item in outcomes["HW-001"].evidence)
    assert "records[0].pid" in hw_001_paths
    assert "records[0].serial_number" in hw_001_paths
    assert "records[10].pid" in hw_001_paths
    assert "records[10].serial_number" in hw_001_paths
    assert all(item.sources for item in outcomes["HW-001"].evidence)

    assert len(outcomes["HW-002"].evidence) == 17
    assert all(item.field_path.startswith("records[") for item in outcomes["HW-002"].evidence)
    assert all(item.sources for item in outcomes["HW-002"].evidence)

    hw_003_paths = tuple(item.field_path for item in outcomes["HW-003"].evidence)
    assert hw_003_paths == tuple(f"records[{index}].component_type" for index in range(17))
    assert all(item.sources for item in outcomes["HW-003"].evidence)

    for outcome in result.outcomes:
        assert all(
            not item.field_path.startswith(("chassis", "modules", "components"))
            for item in outcome.evidence
        )


def test_rules_have_no_functional_dependency_on_legacy_inventory_views() -> None:
    class CanonicalOnlyInventory(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True)

        records: tuple[HardwareInventoryRecord, ...]

    CanonicalOnlyInventory.__name__ = "HardwareInventory"
    model = CanonicalOnlyInventory(
        records=(
            _record(
                1,
                name="Switch 1",
                component_type=HardwareComponentType.CHASSIS_MEMBER,
                pid="C9300-48P",
                serial_number="SERIAL-1",
            ),
            _record(
                2,
                name="Gi1/1/1",
                component_type=HardwareComponentType.TRANSCEIVER,
                serial_number="SERIAL-2",
            ),
        )
    )

    result = AssessmentEngine(hardware_inventory_rule_catalog()).evaluate(model, _context())

    assert tuple(item.status for item in result.outcomes) == (
        AssessmentStatus.PASS,
        AssessmentStatus.PASS,
        AssessmentStatus.INFO,
    )
