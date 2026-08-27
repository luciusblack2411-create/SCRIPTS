from __future__ import annotations

from uuid import uuid4

from cisco_assessment.assessment import (
    SWITCHPORT_OBSERVATION_RULES,
    AdministrativeSwitchportModesObservedRule,
    AssessmentContext,
    AssessmentEngine,
    AssessmentStatus,
    FindingSeverity,
    OperationalSwitchportModesObservedRule,
    RuleCategory,
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


def _outcome(rule: object, model: SwitchportObservation):
    from cisco_assessment.assessment import RuleCatalog

    return AssessmentEngine(RuleCatalog((rule,))).evaluate(model, _context(model.platform)).outcomes[0]


def test_catalog_has_stable_unique_ids_and_contract() -> None:
    catalog = switchport_observation_rule_catalog()

    assert catalog.rules == SWITCHPORT_OBSERVATION_RULES
    assert tuple(rule.metadata.rule_id for rule in catalog.rules) == (
        "SWP-001",
        "SWP-002",
        "SWP-003",
        "SWP-004",
    )
    assert len({rule.metadata.rule_id for rule in catalog.rules}) == 4
    for rule in catalog.rules:
        assert rule.metadata.version == "0.1.0"
        assert rule.metadata.normalized_model == "SwitchportObservation"
        assert rule.metadata.category == RuleCategory.INTERFACES
        assert rule.metadata.severity is FindingSeverity.INFO
        assert rule.metadata.supported_platforms == frozenset(
            {PlatformFamily.IOS, PlatformFamily.IOS_XE}
        )
        assert rule.metadata.required_fields == ("interfaces",)
        assert rule.metadata.evidence_fields == ("interfaces",)
        assert rule.metadata.missing_data_status is AssessmentStatus.ERROR


def test_inventory_reports_interfaces_and_only_demonstrated_enabled_values() -> None:
    model = _observation(
        _record(1, interface="GigabitEthernet1/0/1", switchport_enabled=True),
        _record(2, interface="GigabitEthernet1/0/2", switchport_enabled=None),
    )

    outcome = _outcome(SwitchportInventoryObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert "GigabitEthernet1/0/1" in outcome.message
    assert "GigabitEthernet1/0/2" in outcome.message
    assert tuple(item.field_path for item in outcome.evidence) == (
        "interfaces[0].interface",
        "interfaces[0].switchport_enabled",
        "interfaces[1].interface",
    )


def test_administrative_modes_are_exact_and_neutral() -> None:
    model = _observation(
        _record(1, interface="Gi1/0/1", administrative_mode="dynamic auto"),
        _record(2, interface="Gi1/0/2", administrative_mode="trunk"),
        _record(3, interface="Gi1/0/3", administrative_mode="static access"),
        _record(4, interface="Gi1/0/4", administrative_mode="future mode text"),
    )

    outcome = _outcome(AdministrativeSwitchportModesObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    for value in ("dynamic auto", "trunk", "static access", "future mode text"):
        assert value in outcome.message
        assert value in {item.observed_value for item in outcome.evidence}


def test_mode_rules_pass_when_no_mode_values_are_demonstrated() -> None:
    model = _observation(_record(1, interface="Gi1/0/1"))

    administrative = _outcome(AdministrativeSwitchportModesObservedRule(), model)
    operational = _outcome(OperationalSwitchportModesObservedRule(), model)

    assert administrative.status is AssessmentStatus.PASS
    assert administrative.evidence == ()
    assert operational.status is AssessmentStatus.PASS
    assert operational.evidence == ()


def test_operational_mode_preserves_parenthetical_annotation() -> None:
    mode = "down (suspended member of bundle)"
    model = _observation(_record(1, interface="Gi1/0/1", operational_mode=mode))

    outcome = _outcome(OperationalSwitchportModesObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert mode in outcome.message
    value_evidence = next(
        item for item in outcome.evidence if item.field_path.endswith(".operational_mode")
    )
    assert value_evidence.observed_value == mode


def test_negotiation_true_false_counts_are_factual_and_none_is_omitted() -> None:
    model = _observation(
        _record(1, interface="Gi1/0/1", negotiation_of_trunking=True),
        _record(2, interface="Gi1/0/2", negotiation_of_trunking=False),
        _record(3, interface="Gi1/0/3", negotiation_of_trunking=True),
        _record(4, interface="Gi1/0/4", negotiation_of_trunking=None),
    )

    outcome = _outcome(TrunkNegotiationStatesObservedRule(), model)

    assert outcome.status is AssessmentStatus.INFO
    assert "True=2, False=1" in outcome.message
    assert tuple(
        item.observed_value
        for item in outcome.evidence
        if item.field_path.endswith(".negotiation_of_trunking")
    ) == (True, False, True)
    assert all("interfaces[3].negotiation_of_trunking" != item.field_path for item in outcome.evidence)


def test_none_negotiation_is_neutral_and_has_no_absent_field_evidence() -> None:
    model = _observation(_record(1, interface="Gi1/0/1", negotiation_of_trunking=None))

    outcome = _outcome(TrunkNegotiationStatesObservedRule(), model)

    assert outcome.status is AssessmentStatus.PASS
    assert outcome.evidence == ()


def test_representative_catalog_never_emits_warning_or_fail() -> None:
    model = _observation(
        _record(
            1,
            interface="Gi1/0/1",
            switchport_enabled=True,
            administrative_mode="dynamic auto",
            operational_mode="trunk (member of bundle)",
            negotiation_of_trunking=True,
        ),
        _record(
            2,
            interface="Gi1/0/2",
            switchport_enabled=False,
            administrative_mode="static access",
            operational_mode="down (suspended)",
            negotiation_of_trunking=False,
        ),
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


def test_optional_none_fields_never_generate_requests_for_absent_paths() -> None:
    model = _observation(
        _record(
            1,
            interface="Gi1/0/1",
            switchport_enabled=None,
            administrative_mode=None,
            operational_mode=None,
            negotiation_of_trunking=None,
        )
    )

    result = AssessmentEngine(switchport_observation_rule_catalog()).evaluate(model, _context())
    paths = {
        item.field_path for outcome in result.outcomes for item in outcome.evidence
    }

    assert "interfaces[0].interface" in paths
    assert "interfaces[0].switchport_enabled" not in paths
    assert "interfaces[0].administrative_mode" not in paths
    assert "interfaces[0].operational_mode" not in paths
    assert "interfaces[0].negotiation_of_trunking" not in paths


def test_nxos_is_not_applicable() -> None:
    model = _observation(
        _record(1, interface="Ethernet1/1", administrative_mode="trunk"),
        platform=PlatformFamily.NX_OS,
    )

    result = AssessmentEngine(switchport_observation_rule_catalog()).evaluate(
        model,
        _context(PlatformFamily.NX_OS),
    )

    assert all(outcome.status is AssessmentStatus.NOT_APPLICABLE for outcome in result.outcomes)
    assert all(outcome.reason_code == "unsupported_platform" for outcome in result.outcomes)
    assert result.findings == ()
