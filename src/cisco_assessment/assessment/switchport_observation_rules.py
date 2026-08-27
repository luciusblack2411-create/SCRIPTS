"""Deterministic factual rules for normalized switchport observations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from cisco_assessment.models import SwitchportObservation
from cisco_assessment.models.enums import PlatformFamily

from .catalog import RuleCatalog
from .context import AssessmentContext
from .enums import AssessmentStatus, FindingSeverity, RuleCategory
from .evidence import EvidenceRequest
from .models import RuleDecision, RuleMetadata

_IOS_PLATFORMS = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})
_FieldValue = TypeVar("_FieldValue", str, bool)


def _field_path(index: int, field: str) -> str:
    return f"interfaces[{index}].{field}"


def _interface_evidence(index: int, interface: str) -> EvidenceRequest:
    return EvidenceRequest(
        field_path=_field_path(index, "interface"),
        observed_value=interface,
    )


def _demonstrated_evidence(
    model: SwitchportObservation,
    field: str,
    value: Callable[[int], _FieldValue | None],
) -> tuple[EvidenceRequest, ...]:
    evidence: list[EvidenceRequest] = []
    for index, record in enumerate(model.interfaces):
        observed = value(index)
        if observed is None:
            continue
        evidence.extend(
            (
                _interface_evidence(index, record.interface),
                EvidenceRequest(
                    field_path=_field_path(index, field),
                    observed_value=observed,
                ),
            )
        )
    return tuple(evidence)


def _mode_summary(
    model: SwitchportObservation,
    field: str,
    value: Callable[[int], str | None],
) -> tuple[str, ...]:
    return tuple(
        f"{record.interface}={observed}"
        for index, record in enumerate(model.interfaces)
        if (observed := value(index)) is not None
    )


class SwitchportInventoryObservedRule:
    """Report normalized switchport inventory without inferring health or intent."""

    _metadata = RuleMetadata(
        rule_id="SWP-001",
        version="0.1.0",
        title="Switchport inventory observed",
        description="Reports interfaces present in the normalized switchport observation.",
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="SwitchportObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Use this inventory as factual context without inferring switchport design intent.",
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
        evidence: list[EvidenceRequest] = []
        for index, record in enumerate(model.interfaces):
            evidence.append(_interface_evidence(index, record.interface))
            if record.switchport_enabled is not None:
                evidence.append(
                    EvidenceRequest(
                        field_path=_field_path(index, "switchport_enabled"),
                        observed_value=record.switchport_enabled,
                    )
                )
        names = tuple(record.interface for record in model.interfaces)
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=f"Observed {len(names)} switchport interface(s): " + ", ".join(names) + ".",
            evidence=tuple(evidence),
        )


class AdministrativeSwitchportModesObservedRule:
    """Report demonstrated administrative mode strings exactly as normalized."""

    _metadata = RuleMetadata(
        rule_id="SWP-002",
        version="0.1.0",
        title="Administrative switchport modes observed",
        description="Reports demonstrated administrative switchport mode text without ranking it.",
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="SwitchportObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Treat administrative mode text as factual context until explicit design policy is available.",
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
        get_value = lambda index: model.interfaces[index].administrative_mode
        observations = _mode_summary(model, "administrative_mode", get_value)
        if not observations:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No administrative switchport mode values are demonstrated.",
            )
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=f"Observed {len(observations)} administrative mode value(s): "
            + ", ".join(observations)
            + ".",
            evidence=_demonstrated_evidence(model, "administrative_mode", get_value),
        )


class OperationalSwitchportModesObservedRule:
    """Report demonstrated operational mode strings exactly as normalized."""

    _metadata = RuleMetadata(
        rule_id="SWP-003",
        version="0.1.0",
        title="Operational switchport modes observed",
        description="Reports demonstrated operational switchport mode text without interpreting it.",
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="SwitchportObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Treat operational mode text, including annotations, as factual context only.",
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
        get_value = lambda index: model.interfaces[index].operational_mode
        observations = _mode_summary(model, "operational_mode", get_value)
        if not observations:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No operational switchport mode values are demonstrated.",
            )
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=f"Observed {len(observations)} operational mode value(s): "
            + ", ".join(observations)
            + ".",
            evidence=_demonstrated_evidence(model, "operational_mode", get_value),
        )


class TrunkNegotiationStatesObservedRule:
    """Report demonstrated trunk-negotiation booleans as neutral context."""

    _metadata = RuleMetadata(
        rule_id="SWP-004",
        version="0.1.0",
        title="Trunk negotiation states observed",
        description="Reports counts of demonstrated trunk-negotiation True and False values.",
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="SwitchportObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation="Treat negotiation state as factual context without assigning health or intent.",
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
        get_value = lambda index: model.interfaces[index].negotiation_of_trunking
        demonstrated = tuple(
            value
            for index in range(len(model.interfaces))
            if (value := get_value(index)) is not None
        )
        if not demonstrated:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No normalized trunk-negotiation values are demonstrated.",
            )
        true_count = sum(value is True for value in demonstrated)
        false_count = sum(value is False for value in demonstrated)
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=(
                f"Observed {len(demonstrated)} trunk-negotiation value(s): "
                f"True={true_count}, False={false_count}."
            ),
            evidence=_demonstrated_evidence(model, "negotiation_of_trunking", get_value),
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
