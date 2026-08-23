"""End-to-end read-only orchestration for PR Review Agent v0.1."""

from __future__ import annotations

from collections.abc import Iterable

from cisco_assessment.devtools.pr_review.architecture import evaluate_architecture_safety_checks
from cisco_assessment.devtools.pr_review.check_ids import ReviewCheckId
from cisco_assessment.devtools.pr_review.contract_ci import evaluate_contract_quality_ci_checks
from cisco_assessment.devtools.pr_review.decision import derive_review_decision
from cisco_assessment.devtools.pr_review.enums import ReviewFindingSeverity
from cisco_assessment.devtools.pr_review.github import (
    GitHubReadAdapter,
    GitHubReadBackend,
    PullRequestContext,
)
from cisco_assessment.devtools.pr_review.metadata import evaluate_metadata_checks
from cisco_assessment.devtools.pr_review.models import (
    ReviewFinding,
    ReviewReport,
    ReviewRequest,
)
from cisco_assessment.devtools.pr_review.scope import detected_components, evaluate_scope_checks

_CONTRACT_CHECK_IDS = frozenset({ReviewCheckId.CONTRACT_001, ReviewCheckId.CONTRACT_002})


def review_pr(request: ReviewRequest, backend: GitHubReadBackend) -> ReviewReport:
    """Load one PR through the read-only GitHub boundary and produce a deterministic report."""
    context = GitHubReadAdapter(backend).load_pull_request_context(
        request.repository,
        request.pr_number,
    )
    return build_review_report(request, context)


def build_review_report(request: ReviewRequest, context: PullRequestContext) -> ReviewReport:
    """Compose all implemented v0.1 checks over an already acquired typed context."""
    _validate_request_context_identity(request, context)

    checks = (
        *evaluate_metadata_checks(request, context),
        *evaluate_scope_checks(request, context),
        *evaluate_architecture_safety_checks(context),
        *evaluate_contract_quality_ci_checks(request, context),
    )
    findings = tuple(finding for check in checks for finding in check.findings)
    decision = derive_review_decision(checks, findings)

    return ReviewReport(
        repository=context.repository,
        pr_number=context.pr_number,
        base_branch=context.base_branch,
        base_sha=context.base_sha,
        head_branch=context.head_branch,
        head_sha=context.head_sha,
        mergeable=context.mergeable,
        objective=request.objective,
        detected_components=detected_components(context),
        checks=checks,
        findings=findings,
        contracts_changed=_contract_change_labels(findings),
        contracts_verified_stable=(),
        residual_risks=_residual_risks(findings),
        decision=decision.decision,
        decision_reason=decision.reason,
    )


def _validate_request_context_identity(
    request: ReviewRequest,
    context: PullRequestContext,
) -> None:
    if context.repository != request.repository:
        raise ValueError("review context repository does not match ReviewRequest.repository")
    if context.pr_number != request.pr_number:
        raise ValueError("review context PR number does not match ReviewRequest.pr_number")


def _contract_change_labels(findings: Iterable[ReviewFinding]) -> tuple[str, ...]:
    labels: list[str] = []
    for finding in findings:
        if finding.check_id not in _CONTRACT_CHECK_IDS:
            continue
        for evidence in finding.evidence:
            path = evidence.repository_path or "unknown-path"
            line = str(evidence.line_start) if evidence.line_start is not None else "?"
            observed = evidence.observed_value or "contract change"
            labels.append(f"{path}:{line}: {observed}")
    return tuple(dict.fromkeys(labels))


def _residual_risks(findings: Iterable[ReviewFinding]) -> tuple[str, ...]:
    risks = (
        f"{finding.finding_id}: {finding.title}"
        for finding in findings
        if finding.severity is ReviewFindingSeverity.WARNING
        and not finding.requires_human_decision
    )
    return tuple(dict.fromkeys(risks))
