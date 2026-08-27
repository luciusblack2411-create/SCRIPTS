from __future__ import annotations

from uuid import uuid4

import pytest

from cisco_assessment.assessment import (
    AdministrativeSwitchportModesObservedRule,
    AssessmentContext,
    AssessmentEngine,
    AssessmentRule,
    AssessmentStatus,
    DuplicateRuleError,
    OperationalSwitchportModesObservedRule,
    RuleCatalog,
    RuleOutcome,
    SwitchportInventoryObservedRule,
    TrunkNegotiationStatesObservedRule,
    switchport_observation_rule_catalog,
)
from cisco_assessment.models import SwitchportObservation, SwitchportRecord
from cisco_assessment.models.enums import PlatformFamily


def _record(
    ordinal: int,
    *,
    interface: str,
    switchport_enabled: bool | None = None,
    administrative_mode: str | None = None,
    operational_mode: str | None = None,
    negotiation_of_trunking: bool | None = None,
) -> SwitchportRecord:
    return SwitchportRecord(
        ordinal=ordinal,
        interface=interface,
        switchport_enabled=switchport_enabled,
        administrative_mode=administrative_mode,
        operational_mode=operational_mode,
        access_vlan=None,
        native_vlan=None,
        allowed_vlans=None,
        voice_vlan=None,
        negotiation_of_trunking=negotiation_of_trunking,
    )


def _observation(
    *records: SwitchportRecord,
    platform: PlatformFamily = PlatformFamily.IOS_XE,
) -> SwitchportObservation:
    return SwitchportObservation(platform=platform, interfaces=records)


def _context(platform: PlatformFamily = PlatformFamily.IOS_XE) -> AssessmentContext:
    return AssessmentContext(
        assessment_run_id=uuid4(),
        device_id=uuid4(),
        platform=platform,
    )


def _single_rule_outcome(
    rule: AssessmentRule[SwitchportObservation],
    model: SwitchportObservation,
) -> RuleOutcome:
    catalog = RuleCatalog[SwitchportObservation]((rule,))
    return AssessmentEngine(catalog).evaluate(model, _context(model.platform)).outcomes[0]


def test_catalog_has_stable_unique_ids_and_canonical_contract() -> None:
    catalog = switchport_observation_rule_catalog()

    assert tuple(rule.metadata.rule_id for rule in catalog.rules) == (
        "SWP-001",
        "SWP-002",
        "SWP-003",
        "SWP-004",
    )
    for rule in catalog.rules:
        assert rule.metadata.version == "0.1.0"
        assert rule.metadata.normalized_model == "SwitchportObservation"
        assert rule.metadata.category == "interfaces"
        assert rule.metadata.severity.value == "INFO"
        assert rule.metadata.required_fields == ("interfaces",)
        assert rule.metadata.evidence_fields == ("interfaces",)
        assert rule.metadata.missing_data_status is AssessmentStatus.ERROR
        assert rule.metadata.supported_platforms == frozenset(
            {PlatformFamily.IOS, PlatformFamily.IOS_XE}
        )

    with pytest.raises(DuplicateRuleError):
        RuleCatalog[SwitchportObservation]((catalog.rules[0], catalog.rules[0]))


def test_swp_001_reports_inventory_and_only_demonstrated_switchport_state() -> None:
    model = _observation(
        _record(1, interface="GigabitEthernet1/0/1", switchport_enabled=True),
        _record(2, interface="GigabitEthernet1/0/2", switchport_enabled=None),
    )

    outcome = _single_rule_outcome(SwitchportInventoryObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert (
        outcome.message
        == "Observed 2 interface(s) in the normalized switchport inventory."
    )
    assert tuple(item.field_path for item in outcome.evidence) == (
        "interfaces[0].interface",
        "interfaces[0].switchport_enabled",
        "interfaces[1].interface",
    )


def test_swp_002_preserves_all_administrative_mode_text_in_evidence_without_ranking() -> None:
    modes = ("dynamic auto", "trunk", "static access", "future mode text")
    model = _observation(
        *(
            _record(index, interface=f"GigabitEthernet1/0/{index}", administrative_mode=mode)
            for index, mode in enumerate(modes, start=1)
        )
    )

    outcome = _single_rule_outcome(AdministrativeSwitchportModesObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert (
        outcome.message
        == "Observed 4 demonstrated administrative switchport mode value(s)."
    )
    assert tuple(
        item.observed_value
        for item in outcome.evidence
        if item.field_path.endswith(".administrative_mode")
    ) == modes


def test_swp_002_passes_and_requests_no_optional_mode_evidence_when_absent() -> None:
    model = _observation(_record(1, interface="GigabitEthernet1/0/1"))

    outcome = _single_rule_outcome(AdministrativeSwitchportModesObservedRule(), model)

    assert outcome.status is AssessmentStatus.PASS
    assert outcome.evidence == ()


def test_swp_003_preserves_parenthetical_operational_mode_text_in_evidence() -> None:
    mode = "trunk (member of bundle Po10)"
    model = _observation(
        _record(1, interface="GigabitEthernet1/0/48", operational_mode=mode)
    )

    outcome = _single_rule_outcome(OperationalSwitchportModesObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert (
        outcome.message
        == "Observed 1 demonstrated operational switchport mode value(s)."
    )
    assert outcome.evidence[1].field_path == "interfaces[0].operational_mode"
    assert outcome.evidence[1].observed_value == mode


def test_swp_003_passes_without_demonstrated_operational_modes() -> None:
    model = _observation(_record(1, interface="GigabitEthernet1/0/1"))

    outcome = _single_rule_outcome(OperationalSwitchportModesObservedRule(), model)

    assert outcome.status is AssessmentStatus.PASS
    assert outcome.evidence == ()


def test_swp_004_reports_true_and_false_counts_and_omits_none_evidence() -> None:
    model = _observation(
        _record(1, interface="GigabitEthernet1/0/1", negotiation_of_trunking=True),
        _record(2, interface="GigabitEthernet1/0/2", negotiation_of_trunking=False),
        _record(3, interface="GigabitEthernet1/0/3", negotiation_of_trunking=None),
    )

    outcome = _single_rule_outcome(TrunkNegotiationStatesObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert "True=1, False=1" in outcome.message
    negotiation_evidence = tuple(
        item for item in outcome.evidence if item.field_path.endswith(".negotiation_of_trunking")
    )
    assert tuple(item.observed_value for item in negotiation_evidence) == (True, False)
    assert all("interfaces[2]" not in item.field_path for item in outcome.evidence)


def test_swp_004_passes_when_no_normalized_negotiation_value_is_demonstrated() -> None:
    model = _observation(_record(1, interface="GigabitEthernet1/0/1"))

    outcome = _single_rule_outcome(TrunkNegotiationStatesObservedRule(), model)

    assert outcome.status is AssessmentStatus.PASS
    assert outcome.evidence == ()


def test_v0_1_catalog_never_emits_warning_or_fail_for_valid_observations() -> None:
    model = _observation(
        _record(
            1,
            interface="GigabitEthernet1/0/1",
            switchport_enabled=True,
            administrative_mode="dynamic auto",
            operational_mode="static access (member of bundle Po1)",
            negotiation_of_trunking=True,
        ),
        _record(
            2,
            interface="GigabitEthernet1/0/2",
            switchport_enabled=False,
            administrative_mode="trunk",
            operational_mode="down (suspended member)",
            negotiation_of_trunking=False,
        ),
        _record(3, interface="GigabitEthernet1/0/3"),
    )

    result = AssessmentEngine(switchport_observation_rule_catalog()).evaluate(model, _context())

    assert tuple(outcome.status for outcome in result.outcomes) == (
        AssessmentStatus.INFO,
        AssessmentStatus.INFO,
        AssessmentStatus.INFO,
        AssessmentStatus.INFO,
    )
    assert all(
        outcome.status not in {AssessmentStatus.FAIL, AssessmentStatus.WARNING}
        for outcome in result.outcomes
    )


def test_310_interface_inventory_keeps_swp_messages_bounded_and_evidence_complete() -> None:
    model = _observation(
        *(
            _record(
                ordinal,
                interface=f"GigabitEthernet1/0/{ordinal}",
                switchport_enabled=True,
                administrative_mode="dynamic auto",
                operational_mode="static access",
                negotiation_of_trunking=bool(ordinal % 2),
            )
            for ordinal in range(1, 311)
        )
    )

    result = AssessmentEngine(
        switchport_observation_rule_catalog()
    ).evaluate(
        model,
        _context(),
    )

    outcomes = {
        outcome.rule_id: outcome
        for outcome in result.outcomes
    }

    assert tuple(outcome.status for outcome in result.outcomes) == (
        AssessmentStatus.INFO,
        AssessmentStatus.INFO,
        AssessmentStatus.INFO,
        AssessmentStatus.INFO,
    )

    assert all(
        outcome.status
        not in {
            AssessmentStatus.ERROR,
            AssessmentStatus.WARNING,
            AssessmentStatus.FAIL,
        }
        for outcome in result.outcomes
    )

    assert (
        outcomes["SWP-001"].message
        == "Observed 310 interface(s) in the normalized switchport inventory."
    )

    assert (
        outcomes["SWP-002"].message
        == "Observed 310 demonstrated administrative switchport mode value(s)."
    )

    assert (
        outcomes["SWP-003"].message
        == "Observed 310 demonstrated operational switchport mode value(s)."
    )

    for rule_id in (
        "SWP-001",
        "SWP-002",
        "SWP-003",
    ):
        outcome = outcomes[rule_id]

        assert len(outcome.message) <= 2048
        assert outcome.error_type is None
        assert outcome.error_message is None

    assert len(outcomes["SWP-001"].evidence) == 620
    assert len(outcomes["SWP-002"].evidence) == 620
    assert len(outcomes["SWP-003"].evidence) == 620

    assert (
        outcomes["SWP-001"].evidence[-1].field_path
        == "interfaces[309].switchport_enabled"
    )

    assert (
        outcomes["SWP-002"].evidence[-1].field_path
        == "interfaces[309].administrative_mode"
    )

    assert (
        outcomes["SWP-003"].evidence[-1].field_path
        == "interfaces[309].operational_mode"
    )


def test_catalog_is_not_applicable_to_nxos() -> None:
    model = _observation(
        _record(1, interface="Ethernet1/1", switchport_enabled=True),
        platform=PlatformFamily.NX_OS,
    )

    result = AssessmentEngine(switchport_observation_rule_catalog()).evaluate(
        model,
        _context(PlatformFamily.NX_OS),
    )

    assert all(outcome.status is AssessmentStatus.NOT_APPLICABLE for outcome in result.outcomes)
    assert all(outcome.reason_code == "unsupported_platform" for outcome in result.outcomes)
    assert result.findings == ()
