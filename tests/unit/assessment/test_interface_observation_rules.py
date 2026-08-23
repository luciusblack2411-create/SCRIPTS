from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from cisco_assessment.assessment import (
    AssessmentContext,
    AssessmentEngine,
    AssessmentStatus,
    ConnectedInterfacesObservedRule,
    DisabledInterfacesObservedRule,
    ErrDisabledInterfacesRule,
    NormalizedFieldSource,
    SourceTrace,
    UnrecognizedInterfaceStatusRule,
    interface_observation_rule_catalog,
)
from cisco_assessment.catalog.enums import CommandId
from cisco_assessment.models import (
    CommandExecution,
    InterfaceObservation,
    InterfaceStatusRecord,
    RawCommandOutput,
)
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.parsers import IOSShowInterfacesStatusParser, ParseStatus

FIXTURES = Path(__file__).parents[2] / "fixtures" / "ios" / "show_interfaces_status"
BASELINE_FIXTURE = FIXTURES / "c9300_iosxe_genie_v0_1.txt"


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
    interface: str,
    status: str,
    description: str | None = None,
    vlan: str = "10",
    duplex: str = "auto",
    speed: str = "auto",
    media_type: str | None = None,
) -> InterfaceStatusRecord:
    return InterfaceStatusRecord(
        ordinal=ordinal,
        interface=interface,
        description=description,
        status=status,
        vlan=vlan,
        duplex=duplex,
        speed=speed,
        media_type=media_type,
    )


def _observation(*records: InterfaceStatusRecord) -> InterfaceObservation:
    return InterfaceObservation(platform=PlatformFamily.IOS_XE, interfaces=records)


def _single_rule_outcome(rule: object, model: InterfaceObservation):
    from cisco_assessment.assessment import RuleCatalog

    result = AssessmentEngine(RuleCatalog([rule])).evaluate(model, _context())
    return result.outcomes[0]


def _parsed_baseline() -> tuple[InterfaceObservation, AssessmentContext, RawCommandOutput]:
    execution = CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.INTERFACES_STATUS.value,
        command="show interfaces status",
        sequence=1,
    )
    content = BASELINE_FIXTURE.read_text(encoding="utf-8")
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)
    parsed = IOSShowInterfacesStatusParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )
    assert parsed.status is ParseStatus.SUCCESS

    source_evidence = tuple(
        NormalizedFieldSource(
            normalized_model="InterfaceObservation",
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
    return parsed.data, _context(source_evidence=source_evidence), raw


def test_catalog_has_stable_interface_rule_ids_and_canonical_model_contract() -> None:
    catalog = interface_observation_rule_catalog()

    assert tuple(rule.metadata.rule_id for rule in catalog.rules) == (
        "INT-001",
        "INT-002",
        "INT-003",
        "INT-004",
    )
    for rule in catalog.rules:
        assert rule.metadata.normalized_model == "InterfaceObservation"
        assert rule.metadata.required_fields == ("interfaces",)
        assert rule.metadata.evidence_fields == ("interfaces",)
        assert rule.metadata.category == "interfaces"


def test_int_001_fails_only_for_explicit_err_disabled_observation() -> None:
    model = _observation(
        _record(1, interface="GigabitEthernet1/0/1", status="notconnect"),
        _record(2, interface="GigabitEthernet1/0/2", status="err-disabled"),
    )

    outcome = _single_rule_outcome(ErrDisabledInterfacesRule(), model)

    assert outcome.status is AssessmentStatus.FAIL
    assert "GigabitEthernet1/0/2" in outcome.message
    assert tuple(item.field_path for item in outcome.evidence) == (
        "interfaces[1].interface",
        "interfaces[1].status",
    )
    assert outcome.evidence[1].observed_value == "err-disabled"


def test_int_002_reports_disabled_as_information_without_treating_it_as_failure() -> None:
    model = _observation(
        _record(1, interface="GigabitEthernet1/0/3", status="disabled"),
    )

    outcome = _single_rule_outcome(DisabledInterfacesObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert outcome.severity.value == "INFO"
    assert "disabled state" in outcome.message
    assert outcome.recommendation is not None


def test_int_003_reports_connected_as_operational_information() -> None:
    model = _observation(
        _record(
            1,
            interface="TenGigabitEthernet1/1/1",
            status="connected",
            vlan="routed",
            duplex="full",
            speed="a-10G",
        ),
    )

    outcome = _single_rule_outcome(ConnectedInterfacesObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert "TenGigabitEthernet1/1/1" in outcome.message
    assert tuple(item.field_path for item in outcome.evidence) == (
        "interfaces[0].interface",
        "interfaces[0].status",
    )


def test_notconnect_is_explicitly_neutral_and_produces_no_false_positive() -> None:
    model = _observation(
        _record(
            1,
            interface="GigabitEthernet1/0/10",
            status="notconnect",
            description=None,
            vlan="20",
            duplex="auto",
            speed="auto",
            media_type=None,
        ),
    )

    result = AssessmentEngine(interface_observation_rule_catalog()).evaluate(model, _context())

    assert tuple(outcome.status for outcome in result.outcomes) == (
        AssessmentStatus.PASS,
        AssessmentStatus.PASS,
        AssessmentStatus.PASS,
        AssessmentStatus.PASS,
    )
    assert result.findings == ()


def test_int_004_warns_for_unrecognized_status_and_preserves_observed_token() -> None:
    model = _observation(
        _record(1, interface="GigabitEthernet1/0/20", status="monitoring"),
    )

    outcome = _single_rule_outcome(UnrecognizedInterfaceStatusRule(), model)

    assert outcome.status is AssessmentStatus.WARNING
    assert "GigabitEthernet1/0/20=monitoring" in outcome.message
    assert tuple(item.field_path for item in outcome.evidence) == (
        "interfaces[0].interface",
        "interfaces[0].status",
    )
    assert outcome.evidence[1].observed_value == "monitoring"


def test_multiple_interfaces_and_stack_members_are_evaluated_independently() -> None:
    model = _observation(
        _record(1, interface="GigabitEthernet1/0/1", status="connected"),
        _record(2, interface="GigabitEthernet2/0/3", status="disabled"),
        _record(3, interface="GigabitEthernet2/0/4", status="err-disabled"),
        _record(4, interface="GigabitEthernet1/0/48", status="notconnect"),
    )

    result = AssessmentEngine(interface_observation_rule_catalog()).evaluate(model, _context())
    outcomes = {outcome.rule_id: outcome for outcome in result.outcomes}

    assert outcomes["INT-001"].status is AssessmentStatus.FAIL
    assert "GigabitEthernet2/0/4" in outcomes["INT-001"].message
    assert outcomes["INT-002"].status is AssessmentStatus.INFO
    assert "GigabitEthernet2/0/3" in outcomes["INT-002"].message
    assert outcomes["INT-003"].status is AssessmentStatus.INFO
    assert "GigabitEthernet1/0/1" in outcomes["INT-003"].message
    assert outcomes["INT-004"].status is AssessmentStatus.PASS


def test_port_channel_is_evaluated_by_observed_status_without_interface_type_inference() -> None:
    model = _observation(
        _record(
            1,
            interface="Port-channel10",
            status="connected",
            vlan="trunk",
            duplex="a-full",
            speed="a-10G",
            media_type=None,
        ),
    )

    result = AssessmentEngine(interface_observation_rule_catalog()).evaluate(model, _context())
    outcomes = {outcome.rule_id: outcome for outcome in result.outcomes}

    assert outcomes["INT-001"].status is AssessmentStatus.PASS
    assert outcomes["INT-002"].status is AssessmentStatus.PASS
    assert outcomes["INT-003"].status is AssessmentStatus.INFO
    assert outcomes["INT-004"].status is AssessmentStatus.PASS
    assert "Port-channel10" in outcomes["INT-003"].message


def test_all_runtime_evidence_uses_only_canonical_interfaces_paths() -> None:
    model = _observation(
        _record(1, interface="GigabitEthernet1/0/1", status="connected"),
        _record(2, interface="GigabitEthernet1/0/2", status="disabled"),
        _record(3, interface="GigabitEthernet1/0/3", status="err-disabled"),
        _record(4, interface="GigabitEthernet1/0/4", status="future-state"),
    )

    result = AssessmentEngine(interface_observation_rule_catalog()).evaluate(model, _context())

    for outcome in result.outcomes:
        assert outcome.evidence
        assert all(item.field_path.startswith("interfaces[") for item in outcome.evidence)
        assert all(
            item.field_path.endswith((".interface", ".status")) for item in outcome.evidence
        )


def test_engine_resolves_canonical_interface_evidence_to_parser_field_evidence_and_raw() -> None:
    model, context, raw = _parsed_baseline()

    result = AssessmentEngine(interface_observation_rule_catalog()).evaluate(model, context)
    outcomes = {outcome.rule_id: outcome for outcome in result.outcomes}

    assert [record.status for record in model.interfaces] == [
        "connected",
        "notconnect",
        "disabled",
        "err-disabled",
        "connected",
        "connected",
        "connected",
    ]
    assert outcomes["INT-001"].status is AssessmentStatus.FAIL
    assert outcomes["INT-002"].status is AssessmentStatus.INFO
    assert outcomes["INT-003"].status is AssessmentStatus.INFO
    assert outcomes["INT-004"].status is AssessmentStatus.PASS

    err_disabled_status = next(
        item
        for item in outcomes["INT-001"].evidence
        if item.field_path == "interfaces[3].status"
    )
    assert err_disabled_status.observed_value == "err-disabled"
    assert len(err_disabled_status.sources) == 1
    source = err_disabled_status.sources[0]
    assert source.command_execution_id == raw.command_execution_id
    assert source.raw_output_id == raw.id
    assert source.raw_sha256 == raw.sha256
    assert source.platform is PlatformFamily.IOS_XE
    assert source.line_start == 5
    assert source.line_end == 5

    for outcome in result.outcomes:
        assert all(item.field_path.startswith("interfaces[") for item in outcome.evidence)
        assert all(item.sources for item in outcome.evidence)
