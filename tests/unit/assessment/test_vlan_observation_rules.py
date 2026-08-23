from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from cisco_assessment.assessment import (
    ActiveUnsupportedVlansObservedRule,
    AssessmentContext,
    AssessmentEngine,
    AssessmentRule,
    AssessmentStatus,
    NormalizedFieldSource,
    RuleCatalog,
    SourceTrace,
    SuspendedVlansObservedRule,
    UnknownVlanStatusRule,
    VlanInventoryObservedRule,
    vlan_observation_rule_catalog,
)
from cisco_assessment.catalog.enums import CommandId
from cisco_assessment.models import (
    CommandExecution,
    RawCommandOutput,
    VlanObservation,
    VlanRecord,
    VlanStatus,
)
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.parsers import IOSShowVlanBriefParser, ParseStatus

FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "ios"
    / "show_vlan_brief"
    / "c9300_iosxe_real_sanitized.raw"
)


def _record(
    ordinal: int,
    *,
    vlan_id: int,
    status: VlanStatus = VlanStatus.ACTIVE,
    name: str | None = None,
    ports: tuple[str, ...] | None = (),
) -> VlanRecord:
    return VlanRecord(
        ordinal=ordinal,
        vlan_id=vlan_id,
        name=name,
        status=status,
        ports=ports,
    )


def _observation(
    *records: VlanRecord,
    platform: PlatformFamily = PlatformFamily.IOS_XE,
) -> VlanObservation:
    return VlanObservation(platform=platform, vlans=records)


def _context(
    *,
    platform: PlatformFamily = PlatformFamily.IOS_XE,
    source_evidence: tuple[NormalizedFieldSource, ...] = (),
) -> AssessmentContext:
    run_id = source_evidence[0].source.assessment_run_id if source_evidence else uuid4()
    return AssessmentContext(
        assessment_run_id=run_id,
        device_id=uuid4(),
        platform=platform,
        source_evidence=source_evidence,
    )


def _single_rule_outcome(
    rule: AssessmentRule[VlanObservation],
    model: VlanObservation,
    *,
    platform: PlatformFamily = PlatformFamily.IOS_XE,
):
    catalog = RuleCatalog[VlanObservation]((rule,))
    result = AssessmentEngine(catalog).evaluate(model, _context(platform=platform))
    return result.outcomes[0]


def _parsed_real_fixture() -> tuple[VlanObservation, AssessmentContext, RawCommandOutput]:
    execution = CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.VLANS_BRIEF.value,
        command="show vlan brief",
        sequence=1,
    )
    payload = FIXTURE.read_bytes()
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content=payload.decode("utf-8"),
        encoding="utf-8",
    )
    parsed = IOSShowVlanBriefParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )
    assert parsed.status is ParseStatus.SUCCESS

    source_evidence = tuple(
        NormalizedFieldSource(
            normalized_model="VlanObservation",
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


def test_catalog_has_stable_ids_and_canonical_vlan_contract() -> None:
    catalog = vlan_observation_rule_catalog()

    assert tuple(rule.metadata.rule_id for rule in catalog.rules) == (
        "VLAN-001",
        "VLAN-002",
        "VLAN-003",
        "VLAN-004",
    )
    for rule in catalog.rules:
        assert rule.metadata.normalized_model == "VlanObservation"
        assert rule.metadata.required_fields == ("vlans",)
        assert rule.metadata.evidence_fields == ("vlans",)
        assert rule.metadata.category == "vlan"
        assert rule.metadata.supported_platforms == frozenset(
            {PlatformFamily.IOS, PlatformFamily.IOS_XE}
        )


def test_vlan_001_reports_inventory_as_information() -> None:
    model = _observation(
        _record(1, vlan_id=1, name="default"),
        _record(2, vlan_id=20, name="USERS"),
    )

    outcome = _single_rule_outcome(VlanInventoryObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert "Observed 2 VLAN(s)" in outcome.message
    assert tuple(item.field_path for item in outcome.evidence) == (
        "vlans[0].vlan_id",
        "vlans[1].vlan_id",
    )


def test_vlan_002_passes_without_suspended_vlan_and_warns_at_first_suspended_vlan() -> None:
    active_model = _observation(_record(1, vlan_id=10, status=VlanStatus.ACTIVE))
    suspended_model = _observation(
        _record(1, vlan_id=10, status=VlanStatus.ACTIVE),
        _record(2, vlan_id=20, status=VlanStatus.SUSPENDED),
    )

    passed = _single_rule_outcome(SuspendedVlansObservedRule(), active_model)
    warned = _single_rule_outcome(SuspendedVlansObservedRule(), suspended_model)

    assert passed.status is AssessmentStatus.PASS
    assert warned.status is AssessmentStatus.WARNING
    assert "20" in warned.message
    assert tuple(item.field_path for item in warned.evidence) == (
        "vlans[1].vlan_id",
        "vlans[1].status",
    )


def test_vlan_003_warns_only_for_unknown_normalized_status() -> None:
    known_model = _observation(
        _record(1, vlan_id=10, status=VlanStatus.ACTIVE),
        _record(2, vlan_id=20, status=VlanStatus.SUSPENDED),
        _record(3, vlan_id=1002, status=VlanStatus.ACTIVE_UNSUPPORTED),
    )
    unknown_model = _observation(
        _record(1, vlan_id=10, status=VlanStatus.ACTIVE),
        _record(2, vlan_id=20, status=VlanStatus.UNKNOWN),
    )

    passed = _single_rule_outcome(UnknownVlanStatusRule(), known_model)
    warned = _single_rule_outcome(UnknownVlanStatusRule(), unknown_model)

    assert passed.status is AssessmentStatus.PASS
    assert warned.status is AssessmentStatus.WARNING
    assert "20" in warned.message
    assert warned.evidence[1].field_path == "vlans[1].status"
    assert warned.evidence[1].observed_value == "unknown"


def test_vlan_004_treats_act_unsup_as_information_not_failure() -> None:
    model = _observation(
        _record(1, vlan_id=1002, status=VlanStatus.ACTIVE_UNSUPPORTED),
        _record(2, vlan_id=1003, status=VlanStatus.ACTIVE_UNSUPPORTED),
        _record(3, vlan_id=1004, status=VlanStatus.ACTIVE_UNSUPPORTED),
        _record(4, vlan_id=1005, status=VlanStatus.ACTIVE_UNSUPPORTED),
    )

    outcome = _single_rule_outcome(ActiveUnsupportedVlansObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert "1002, 1003, 1004, 1005" in outcome.message
    assert all(item.observed_value != "unknown" for item in outcome.evidence)
    assert all(
        item.field_path.endswith((".vlan_id", ".status")) for item in outcome.evidence
    )


def test_vlan_004_passes_when_act_unsup_is_absent() -> None:
    model = _observation(_record(1, vlan_id=10, status=VlanStatus.ACTIVE))

    outcome = _single_rule_outcome(ActiveUnsupportedVlansObservedRule(), model)

    assert outcome.status is AssessmentStatus.PASS


def test_ports_empty_unknown_or_multiline_population_do_not_change_rule_health() -> None:
    vlan1_ports = tuple(f"Gi1/0/{index}" for index in range(1, 55))
    model = _observation(
        _record(1, vlan_id=1, status=VlanStatus.ACTIVE, ports=vlan1_ports),
        _record(2, vlan_id=20, status=VlanStatus.ACTIVE, ports=()),
        _record(3, vlan_id=30, status=VlanStatus.ACTIVE, ports=None),
    )

    result = AssessmentEngine(vlan_observation_rule_catalog()).evaluate(model, _context())
    outcomes = {outcome.rule_id: outcome for outcome in result.outcomes}

    assert outcomes["VLAN-001"].status is AssessmentStatus.INFO
    assert outcomes["VLAN-002"].status is AssessmentStatus.PASS
    assert outcomes["VLAN-003"].status is AssessmentStatus.PASS
    assert outcomes["VLAN-004"].status is AssessmentStatus.PASS
    assert all(outcome.status is not AssessmentStatus.FAIL for outcome in result.outcomes)
    assert all(
        ".ports" not in evidence.field_path
        for outcome in result.outcomes
        for evidence in outcome.evidence
    )


def test_v0_1_catalog_does_not_invent_fail_without_explicit_policy() -> None:
    model = _observation(
        _record(1, vlan_id=10, status=VlanStatus.SUSPENDED),
        _record(2, vlan_id=20, status=VlanStatus.UNKNOWN),
        _record(3, vlan_id=1002, status=VlanStatus.ACTIVE_UNSUPPORTED),
    )

    result = AssessmentEngine(vlan_observation_rule_catalog()).evaluate(model, _context())

    assert tuple(outcome.status for outcome in result.outcomes) == (
        AssessmentStatus.INFO,
        AssessmentStatus.WARNING,
        AssessmentStatus.WARNING,
        AssessmentStatus.INFO,
    )
    assert all(outcome.status is not AssessmentStatus.FAIL for outcome in result.outcomes)


def test_catalog_is_not_applicable_to_nxos_until_platform_support_exists() -> None:
    model = _observation(
        _record(1, vlan_id=10),
        platform=PlatformFamily.NX_OS,
    )

    result = AssessmentEngine(vlan_observation_rule_catalog()).evaluate(
        model,
        _context(platform=PlatformFamily.NX_OS),
    )

    assert all(outcome.status is AssessmentStatus.NOT_APPLICABLE for outcome in result.outcomes)
    assert all(outcome.reason_code == "unsupported_platform" for outcome in result.outcomes)
    assert result.findings == (result.findings[0],) if result.findings else ()
    assert result.findings == ()


def test_real_17_vlan_fixture_preserves_conservative_outcomes_and_raw_traceability() -> None:
    model, context, raw = _parsed_real_fixture()

    assert len(model.vlans) == 17
    assert len(model.vlans[0].ports or ()) == 54
    assert all(record.ports == () for record in model.vlans[1:])
    assert [record.status for record in model.vlans[13:]] == [
        VlanStatus.ACTIVE_UNSUPPORTED,
        VlanStatus.ACTIVE_UNSUPPORTED,
        VlanStatus.ACTIVE_UNSUPPORTED,
        VlanStatus.ACTIVE_UNSUPPORTED,
    ]

    result = AssessmentEngine(vlan_observation_rule_catalog()).evaluate(model, context)
    outcomes = {outcome.rule_id: outcome for outcome in result.outcomes}

    assert outcomes["VLAN-001"].status is AssessmentStatus.INFO
    assert outcomes["VLAN-002"].status is AssessmentStatus.PASS
    assert outcomes["VLAN-003"].status is AssessmentStatus.PASS
    assert outcomes["VLAN-004"].status is AssessmentStatus.INFO
    assert all(outcome.status is not AssessmentStatus.FAIL for outcome in result.outcomes)

    first_vlan_id = next(
        item for item in outcomes["VLAN-001"].evidence if item.field_path == "vlans[0].vlan_id"
    )
    assert first_vlan_id.observed_value == 1
    assert len(first_vlan_id.sources) == 1
    assert first_vlan_id.sources[0].raw_output_id == raw.id
    assert first_vlan_id.sources[0].command_execution_id == raw.command_execution_id
    assert first_vlan_id.sources[0].raw_sha256 == raw.sha256
    assert first_vlan_id.sources[0].line_start == 5
    assert first_vlan_id.sources[0].line_end == 5

    vlan_1002_status = next(
        item for item in outcomes["VLAN-004"].evidence if item.field_path == "vlans[13].status"
    )
    assert vlan_1002_status.observed_value == "act/unsup"
    assert len(vlan_1002_status.sources) == 1
    assert vlan_1002_status.sources[0].raw_output_id == raw.id
    assert vlan_1002_status.sources[0].raw_sha256 == raw.sha256
    assert vlan_1002_status.sources[0].line_start == 38
    assert vlan_1002_status.sources[0].line_end == 38

    for outcome in result.outcomes:
        assert outcome.evidence
        assert all(item.field_path.startswith("vlans[") for item in outcome.evidence)
        assert all(
            item.field_path.endswith((".vlan_id", ".status")) for item in outcome.evidence
        )
        assert all(item.sources for item in outcome.evidence)
