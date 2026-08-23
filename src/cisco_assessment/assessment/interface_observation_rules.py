"""Deterministic InterfaceObservation assessment rules over canonical interfaces."""

from __future__ import annotations

from collections.abc import Iterable

from cisco_assessment.models import InterfaceObservation
from cisco_assessment.models.enums import PlatformFamily

from .catalog import RuleCatalog
from .context import AssessmentContext
from .enums import AssessmentStatus, FindingSeverity, RuleCategory
from .evidence import EvidenceRequest
from .models import RuleDecision, RuleMetadata

_IOS_PLATFORMS = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})
_HANDLED_STATUSES = frozenset({"connected", "notconnect", "disabled", "err-disabled"})


def _interface_field_path(index: int, field: str) -> str:
    return f"interfaces[{index}].{field}"


def _status_key(status: str) -> str:
    return status.casefold()


def _matching_indexes(model: InterfaceObservation, status: str) -> tuple[int, ...]:
    expected = _status_key(status)
    return tuple(
        index
        for index, record in enumerate(model.interfaces)
        if _status_key(record.status) == expected
    )


def _status_evidence(
    model: InterfaceObservation,
    indexes: Iterable[int] | None = None,
) -> tuple[EvidenceRequest, ...]:
    selected = tuple(range(len(model.interfaces))) if indexes is None else tuple(indexes)
    evidence: list[EvidenceRequest] = []
    for index in selected:
        record = model.interfaces[index]
        evidence.extend(
            (
                EvidenceRequest(
                    field_path=_interface_field_path(index, "interface"),
                    observed_value=record.interface,
                ),
                EvidenceRequest(
                    field_path=_interface_field_path(index, "status"),
                    observed_value=record.status,
                ),
            )
        )
    return tuple(evidence)


class ErrDisabledInterfacesRule:
    """Fail when one or more interfaces are explicitly observed err-disabled."""

    _metadata = RuleMetadata(
        rule_id="INT-001",
        version="0.1.0",
        title="Err-disabled interfaces observed",
        description=(
            "Checks for interfaces whose observed show interfaces status state is err-disabled."
        ),
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.MEDIUM,
        normalized_model="InterfaceObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Review the err-disable cause and the affected interface before restoring service; "
            "do not infer the cause from interface status alone."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: InterfaceObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes = _matching_indexes(model, "err-disabled")
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No interfaces are currently observed in err-disabled state.",
                evidence=_status_evidence(model),
            )

        names = tuple(model.interfaces[index].interface for index in indexes)
        return RuleDecision(
            status=AssessmentStatus.FAIL,
            message=(
                f"{len(indexes)} interface(s) are currently observed in err-disabled state: "
                + ", ".join(names)
                + "."
            ),
            evidence=_status_evidence(model, indexes),
        )


class DisabledInterfacesObservedRule:
    """Report administratively disabled observations without treating them as faults."""

    _metadata = RuleMetadata(
        rule_id="INT-002",
        version="0.1.0",
        title="Disabled interfaces observed",
        description=(
            "Reports interfaces whose observed show interfaces status state is disabled."
        ),
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="InterfaceObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Use disabled interfaces as factual inventory context and compare them with intended "
            "design only when that design information is available."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: InterfaceObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes = _matching_indexes(model, "disabled")
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No interfaces are currently observed in disabled state.",
                evidence=_status_evidence(model),
            )

        names = tuple(model.interfaces[index].interface for index in indexes)
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=(
                f"{len(indexes)} interface(s) are currently observed in disabled state: "
                + ", ".join(names)
                + "."
            ),
            evidence=_status_evidence(model, indexes),
        )


class ConnectedInterfacesObservedRule:
    """Report interfaces currently observed connected as operational context."""

    _metadata = RuleMetadata(
        rule_id="INT-003",
        version="0.1.0",
        title="Connected interfaces observed",
        description=(
            "Reports interfaces whose observed show interfaces status state is connected."
        ),
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.INFO,
        normalized_model="InterfaceObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Use connected state as operational context only; correlate with other normalized "
            "domains before drawing design, redundancy, or health conclusions."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: InterfaceObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes = _matching_indexes(model, "connected")
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No interfaces are currently observed in connected state.",
                evidence=_status_evidence(model),
            )

        names = tuple(model.interfaces[index].interface for index in indexes)
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=(
                f"{len(indexes)} interface(s) are currently observed in connected state: "
                + ", ".join(names)
                + "."
            ),
            evidence=_status_evidence(model, indexes),
        )


class UnrecognizedInterfaceStatusRule:
    """Flag observed interface states outside the explicitly handled v0.1 vocabulary."""

    _metadata = RuleMetadata(
        rule_id="INT-004",
        version="0.1.0",
        title="Unrecognized interface status observed",
        description=(
            "Checks for observed interface status tokens outside connected, notconnect, disabled, "
            "and err-disabled."
        ),
        category=RuleCategory.INTERFACES,
        severity=FindingSeverity.LOW,
        normalized_model="InterfaceObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("interfaces",),
        evidence_fields=("interfaces",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Review unfamiliar status tokens against the source CLI and platform documentation "
            "before assigning assessment semantics or extending the handled vocabulary."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: InterfaceObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes = tuple(
            index
            for index, record in enumerate(model.interfaces)
            if _status_key(record.status) not in _HANDLED_STATUSES
        )
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="All observed interface status tokens are explicitly handled by v0.1 rules.",
                evidence=_status_evidence(model),
            )

        observations = tuple(
            f"{model.interfaces[index].interface}={model.interfaces[index].status}"
            for index in indexes
        )
        return RuleDecision(
            status=AssessmentStatus.WARNING,
            message=(
                f"{len(indexes)} interface(s) have status tokens requiring review: "
                + ", ".join(observations)
                + "."
            ),
            evidence=_status_evidence(model, indexes),
        )


INTERFACE_OBSERVATION_RULES = (
    ErrDisabledInterfacesRule(),
    DisabledInterfacesObservedRule(),
    ConnectedInterfacesObservedRule(),
    UnrecognizedInterfaceStatusRule(),
)


def interface_observation_rule_catalog() -> RuleCatalog[InterfaceObservation]:
    """Return the immutable InterfaceObservation v0.1 rule catalog."""

    return RuleCatalog[InterfaceObservation](INTERFACE_OBSERVATION_RULES)
