"""Deterministic VlanObservation assessment rules over canonical VLAN records."""

from __future__ import annotations

from collections.abc import Iterable

from cisco_assessment.models import VlanObservation, VlanStatus
from cisco_assessment.models.enums import PlatformFamily

from .catalog import RuleCatalog
from .context import AssessmentContext
from .enums import AssessmentStatus, FindingSeverity, RuleCategory
from .evidence import EvidenceRequest
from .models import RuleDecision, RuleMetadata

_IOS_PLATFORMS = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})


def _vlan_field_path(index: int, field: str) -> str:
    return f"vlans[{index}].{field}"


def _vlan_identity_evidence(
    model: VlanObservation,
    indexes: Iterable[int] | None = None,
    *,
    include_status: bool = True,
) -> tuple[EvidenceRequest, ...]:
    selected = tuple(range(len(model.vlans))) if indexes is None else tuple(indexes)
    evidence: list[EvidenceRequest] = []
    for index in selected:
        record = model.vlans[index]
        evidence.append(
            EvidenceRequest(
                field_path=_vlan_field_path(index, "vlan_id"),
                observed_value=record.vlan_id,
            )
        )
        if include_status:
            evidence.append(
                EvidenceRequest(
                    field_path=_vlan_field_path(index, "status"),
                    observed_value=record.status.value,
                )
            )
    return tuple(evidence)


def _matching_status_indexes(
    model: VlanObservation,
    status: VlanStatus,
) -> tuple[int, ...]:
    return tuple(
        index
        for index, record in enumerate(model.vlans)
        if record.status is status
    )


class VlanInventoryObservedRule:
    """Record the authoritative VLAN inventory observed by ``show vlan brief``."""

    _metadata = RuleMetadata(
        rule_id="VLAN-001",
        version="0.1.0",
        title="VLAN inventory observed",
        description="Records the VLANs present in the normalized show vlan brief observation.",
        category=RuleCategory.VLAN,
        severity=FindingSeverity.INFO,
        normalized_model="VlanObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("vlans",),
        evidence_fields=("vlans",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Use this VLAN inventory as factual baseline data; correlate it with other domains only "
            "when those domains provide their own normalized evidence."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: VlanObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        vlan_ids = tuple(record.vlan_id for record in model.vlans)
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=(
                f"Observed {len(vlan_ids)} VLAN(s) in the normalized VLAN inventory: "
                + ", ".join(str(vlan_id) for vlan_id in vlan_ids)
                + "."
            ),
            evidence=_vlan_identity_evidence(model, include_status=False),
        )


class SuspendedVlansObservedRule:
    """Warn when VLANs are explicitly observed in suspended state."""

    _metadata = RuleMetadata(
        rule_id="VLAN-002",
        version="0.1.0",
        title="Suspended VLANs observed",
        description="Checks for VLAN records whose normalized status is suspend.",
        category=RuleCategory.VLAN,
        severity=FindingSeverity.LOW,
        normalized_model="VlanObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("vlans",),
        evidence_fields=("vlans",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Review whether each suspended VLAN is intentional before assigning configuration or "
            "service impact; this observation alone does not establish design intent."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: VlanObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes = _matching_status_indexes(model, VlanStatus.SUSPENDED)
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No VLANs are explicitly observed in suspended state.",
                evidence=_vlan_identity_evidence(model),
            )

        vlan_ids = tuple(model.vlans[index].vlan_id for index in indexes)
        return RuleDecision(
            status=AssessmentStatus.WARNING,
            message=(
                f"{len(indexes)} VLAN(s) are explicitly observed in suspended state: "
                + ", ".join(str(vlan_id) for vlan_id in vlan_ids)
                + "."
            ),
            evidence=_vlan_identity_evidence(model, indexes),
        )


class UnknownVlanStatusRule:
    """Warn when the parser cannot map an observed VLAN status to the v0.1 vocabulary."""

    _metadata = RuleMetadata(
        rule_id="VLAN-003",
        version="0.1.0",
        title="Unknown VLAN status observed",
        description="Checks for VLAN records whose normalized status is unknown.",
        category=RuleCategory.VLAN,
        severity=FindingSeverity.LOW,
        normalized_model="VlanObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("vlans",),
        evidence_fields=("vlans",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Review the source CLI and platform documentation before assigning semantics to an "
            "unknown VLAN status or extending the normalized vocabulary."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: VlanObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes = _matching_status_indexes(model, VlanStatus.UNKNOWN)
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="All observed VLAN statuses are represented by the v0.1 vocabulary.",
                evidence=_vlan_identity_evidence(model),
            )

        vlan_ids = tuple(model.vlans[index].vlan_id for index in indexes)
        return RuleDecision(
            status=AssessmentStatus.WARNING,
            message=(
                f"{len(indexes)} VLAN(s) have an unknown normalized status requiring review: "
                + ", ".join(str(vlan_id) for vlan_id in vlan_ids)
                + "."
            ),
            evidence=_vlan_identity_evidence(model, indexes),
        )


class ActiveUnsupportedVlansObservedRule:
    """Report Cisco ``act/unsup`` VLAN status as platform context, not failure."""

    _metadata = RuleMetadata(
        rule_id="VLAN-004",
        version="0.1.0",
        title="Active unsupported VLAN status observed",
        description="Reports VLAN records whose normalized status is act/unsup.",
        category=RuleCategory.VLAN,
        severity=FindingSeverity.INFO,
        normalized_model="VlanObservation",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("vlans",),
        evidence_fields=("vlans",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Treat act/unsup as platform-reported VLAN context. Do not classify it as a failure "
            "without an explicit policy requiring local support or use of the affected VLAN."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(
        self,
        model: VlanObservation,
        context: AssessmentContext,
    ) -> RuleDecision:
        del context
        indexes = _matching_status_indexes(model, VlanStatus.ACTIVE_UNSUPPORTED)
        if not indexes:
            return RuleDecision(
                status=AssessmentStatus.PASS,
                message="No VLANs are observed with act/unsup status.",
                evidence=_vlan_identity_evidence(model),
            )

        vlan_ids = tuple(model.vlans[index].vlan_id for index in indexes)
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=(
                f"{len(indexes)} VLAN(s) are observed with act/unsup status: "
                + ", ".join(str(vlan_id) for vlan_id in vlan_ids)
                + "."
            ),
            evidence=_vlan_identity_evidence(model, indexes),
        )


VLAN_OBSERVATION_RULES = (
    VlanInventoryObservedRule(),
    SuspendedVlansObservedRule(),
    UnknownVlanStatusRule(),
    ActiveUnsupportedVlansObservedRule(),
)


def vlan_observation_rule_catalog() -> RuleCatalog[VlanObservation]:
    """Return the immutable VlanObservation v0.1 rule catalog."""

    return RuleCatalog[VlanObservation](VLAN_OBSERVATION_RULES)
