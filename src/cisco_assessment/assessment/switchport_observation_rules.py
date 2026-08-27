"""Deterministic SwitchportObservation rules over normalized interface records."""

from __future__ import annotations

from collections.abc import Iterable

from cisco_assessment.models import SwitchportObservation
from cisco_assessment.models.enums import PlatformFamily

from .catalog import RuleCatalog
from .context import AssessmentContext
from .enums import AssessmentStatus, FindingSeverity, RuleCategory
from .evidence import EvidenceRequest
from .models import RuleDecision, RuleMetadata

_IOS_PLATFORMS = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})


def _interface_field_path(index: int, field: str) -> str:
    return f"interfaces[{index}].{field}"


def _field_evidence(
    model: SwitchportObservation,
    field: str,
    indexes: Iterable[int],
) -> tuple[EvidenceRequest, ...]:
    evidence: list[EvidenceRequest] = []
    for index in indexes:
        record = model.interfaces[index]
        evidence.append(
            EvidenceRequest(
                field_path=_interface_field_path(index, "interface"),
                observed_value=record.interface,
            )
        )
        value: str | bool | None
        if field == "switchport_enabled":
            value = record.switchport_enabled
        elif field == "administrative_mode":
            value = record.administrative_mode
        elif field == "operational_mode":
            value = record.operational_mode
        elif field == "negotiation_of_trunking":
            value = record.negotiation_of_trunking
        else:
            raise ValueError(f"unsupported switchport evidence field: {field}")
        if value is not None:
            evidence.append(
                EvidenceRequest(
                    field_path=_interface_field_path(index, field),
                    observed_value=value,
                )
            )
    return tuple(evidence)


class SwitchportInventoryObservedRule:
    """Report the normalized switchport interface inventory factually."""

    _metadata = RuleMetadata(
        rule_id="SWP-001",
        version="0.1.0",
        title="Switchport inventory observed",
        description="Records interfaces present in the normalized switchport observation.",
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="SwitchportObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Use this inventory as factual switchport context only.",
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: SwitchportObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        names = tuple(record.interface for record in model.interfaces)
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=(
                f"Observed {len(names)} interface(s) in the normalized switchport inventory."
            ),
            evidence=_field_evidence(
                model,
                "switchport_enabled",
                range(len(model.interfaces)),
            ),
        )


class AdministrativeSwitchportModesObservedRule:
    """Report demonstrated administrative mode strings without interpretation."""

    _metadata = RuleMetadata(
        rule_id="SWP-002",
        version="0.1.0",
        title="Administrative switchport modes observed",
        description="Reports demonstrated administrative switchport mode strings factually.",
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="SwitchportObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Compare observed modes with design intent only when authoritative intent exists.",
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: SwitchportObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes = tuple(
            index
            for index, record in enumerate(model.interfaces)
            if record.administrative_mode is not None
        )
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No administrative switchport mode values are demonstrated.",
            )
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=(
                f"Observed {len(indexes)} demonstrated administrative switchport mode value(s)."
            ),
            evidence=_field_evidence(model, "administrative_mode", indexes),
        )


class OperationalSwitchportModesObservedRule:
    """Report demonstrated operational mode strings without interpretation."""

    _metadata = RuleMetadata(
        rule_id="SWP-003",
        version="0.1.0",
        title="Operational switchport modes observed",
        description="Reports demonstrated operational switchport mode strings factually.",
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="SwitchportObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Treat operational mode text as observed context without inferring health.",
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: SwitchportObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes = tuple(
            index
            for index, record in enumerate(model.interfaces)
            if record.operational_mode is not None
        )
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No operational switchport mode values are demonstrated.",
            )
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=(
                f"Observed {len(indexes)} demonstrated operational switchport mode value(s)."
            ),
            evidence=_field_evidence(model, "operational_mode", indexes),
        )


class TrunkNegotiationStatesObservedRule:
    """Report demonstrated trunk-negotiation boolean states factually."""

    _metadata = RuleMetadata(
        rule_id="SWP-004",
        version="0.1.0",
        title="Trunk negotiation states observed",
        description="Reports counts of demonstrated trunk-negotiation boolean states.",
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="SwitchportObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Treat negotiation state as factual context without assigning health semantics.",
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: SwitchportObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes: list[int] = []
        enabled_count = 0
        disabled_count = 0
        for index, record in enumerate(model.interfaces):
            state = record.negotiation_of_trunking
            if state is None:
                continue
            indexes.append(index)
            if state:
                enabled_count += 1
            else:
                disabled_count += 1
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No normalized trunk negotiation states are demonstrated.",
            )
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=(
                f"Observed {len(indexes)} demonstrated trunk negotiation state(s): "
                f"True={enabled_count}, False={disabled_count}."
            ),
            evidence=_field_evidence(model, "negotiation_of_trunking", indexes),
        )


SWITCHPORT_OBSERVATION_RULES = (
    SwitchportInventoryObservedRule(),
    AdministrativeSwitchportModesObservedRule(),
    OperationalSwitchportModesObservedRule(),
    TrunkNegotiationStatesObservedRule(),
)


def switchport_observation_rule_catalog() -> RuleCatalog[SwitchportObservation]:
    """Return the immutable SwitchportObservation v0.1 rule catalog."""

    return RuleCatalog[SwitchportObservation](SWITCHPORT_OBSERVATION_RULES)
