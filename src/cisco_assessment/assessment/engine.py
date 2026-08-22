"""Deterministic assessment rule execution engine."""

from __future__ import annotations

from typing import Generic, TypeVar
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel

from .catalog import RuleCatalog
from .context import AssessmentContext
from .enums import AssessmentStatus
from .evidence import EvidenceRequest, FindingEvidence
from .models import AssessmentResult, Finding, RuleOutcome
from .rules import AssessmentRule

NormalizedT = TypeVar("NormalizedT", bound=BaseModel)

_FINDING_STATUSES = frozenset(
    {
        AssessmentStatus.FAIL,
        AssessmentStatus.WARNING,
        AssessmentStatus.INFO,
        AssessmentStatus.ERROR,
    }
)


class AssessmentEngine(Generic[NormalizedT]):
    """Execute a catalog of deterministic rules against normalized data."""

    def __init__(self, catalog: RuleCatalog[NormalizedT]) -> None:
        self._catalog = catalog

    def evaluate(self, model: NormalizedT, context: AssessmentContext) -> AssessmentResult:
        """Evaluate every catalog rule without allowing one failure to abort the run."""
        normalized_model = type(model).__name__
        outcomes: list[RuleOutcome] = []
        findings: list[Finding] = []

        for rule in self._catalog.rules:
            outcome = self._execute_rule(
                rule=rule,
                model=model,
                context=context,
                normalized_model=normalized_model,
            )
            outcomes.append(outcome)

            finding = self._to_finding(outcome, context)
            if finding is not None:
                findings.append(finding)

        return AssessmentResult(
            assessment_run_id=context.assessment_run_id,
            device_id=context.device_id,
            platform=context.platform,
            normalized_model=normalized_model,
            outcomes=tuple(outcomes),
            findings=tuple(findings),
        )

    def _execute_rule(
        self,
        *,
        rule: AssessmentRule[NormalizedT],
        model: NormalizedT,
        context: AssessmentContext,
        normalized_model: str,
    ) -> RuleOutcome:
        metadata = rule.metadata

        if metadata.normalized_model != normalized_model:
            return RuleOutcome(
                rule_id=metadata.rule_id,
                rule_version=metadata.version,
                title=metadata.title,
                category=metadata.category,
                normalized_model=metadata.normalized_model,
                status=AssessmentStatus.NOT_APPLICABLE,
                severity=metadata.severity,
                message=f"Rule expects {metadata.normalized_model}; received {normalized_model}.",
                reason_code="unsupported_normalized_model",
            )

        if context.platform not in metadata.supported_platforms:
            return RuleOutcome(
                rule_id=metadata.rule_id,
                rule_version=metadata.version,
                title=metadata.title,
                category=metadata.category,
                normalized_model=metadata.normalized_model,
                status=AssessmentStatus.NOT_APPLICABLE,
                severity=metadata.severity,
                message=f"Rule does not apply to platform {context.platform.value}.",
                reason_code="unsupported_platform",
            )

        try:
            decision = rule.evaluate(model, context)
        except Exception as exc:
            return RuleOutcome(
                rule_id=metadata.rule_id,
                rule_version=metadata.version,
                title=metadata.title,
                category=metadata.category,
                normalized_model=metadata.normalized_model,
                status=AssessmentStatus.ERROR,
                severity=metadata.severity,
                message="Rule execution failed.",
                reason_code="rule_execution_error",
                error_type=type(exc).__name__,
                error_message=str(exc) or None,
            )

        evidence = tuple(
            self._resolve_evidence(
                request=request,
                normalized_model=metadata.normalized_model,
                context=context,
            )
            for request in decision.evidence
        )

        return RuleOutcome(
            rule_id=metadata.rule_id,
            rule_version=metadata.version,
            title=metadata.title,
            category=metadata.category,
            normalized_model=metadata.normalized_model,
            status=decision.status,
            severity=metadata.severity,
            message=decision.message,
            evidence=evidence,
            recommendation=decision.recommendation,
        )

    @staticmethod
    def _resolve_evidence(
        *,
        request: EvidenceRequest,
        normalized_model: str,
        context: AssessmentContext,
    ) -> FindingEvidence:
        return FindingEvidence(
            normalized_model=normalized_model,
            field_path=request.field_path,
            observed_value=request.observed_value,
            sources=context.sources_for(normalized_model, request.field_path),
        )

    @staticmethod
    def _to_finding(outcome: RuleOutcome, context: AssessmentContext) -> Finding | None:
        if outcome.status not in _FINDING_STATUSES:
            return None

        finding_id = uuid5(
            NAMESPACE_URL,
            (
                "cisco-assessment:"
                f"{context.assessment_run_id}:{context.device_id}:{outcome.rule_id}"
            ),
        )
        return Finding(
            finding_id=finding_id,
            rule_id=outcome.rule_id,
            rule_version=outcome.rule_version,
            title=outcome.title,
            description=outcome.message,
            category=outcome.category,
            normalized_model=outcome.normalized_model,
            status=outcome.status,
            severity=outcome.severity,
            evidence=outcome.evidence,
            recommendation=outcome.recommendation,
            error_type=outcome.error_type,
            error_message=outcome.error_message,
        )
