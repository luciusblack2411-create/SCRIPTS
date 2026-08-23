"""Deterministic merge-ref CI provenance check for PR Review Agent v0.1."""

from __future__ import annotations

from cisco_assessment.devtools.pr_review.check_ids import ReviewCheckId
from cisco_assessment.devtools.pr_review.enums import (
    ReviewCheckStatus,
    ReviewEvidenceKind,
    ReviewFindingSeverity,
)
from cisco_assessment.devtools.pr_review.github import GitHubWorkflowRun, PullRequestContext
from cisco_assessment.devtools.pr_review.models import (
    ReviewCheck,
    ReviewEvidence,
    ReviewFinding,
    ReviewRequest,
)


def evaluate_ci_merge_provenance(
    request: ReviewRequest,
    context: PullRequestContext,
) -> ReviewCheck:
    """Prove that successful CI tested the current PR head merged into the current base."""
    check_id = ReviewCheckId.CI_003
    name = "Successful CI proves the current pull-request merge checkout"
    if not request.require_ci_success:
        return ReviewCheck(
            check_id=check_id,
            name=name,
            category="CI",
            status=ReviewCheckStatus.NOT_APPLICABLE,
            applicable=False,
            summary="The review request does not require CI success.",
            evidence=(),
            findings=(),
            blocking=True,
        )
    if context.base_branch_head_sha is None:
        return _unknown(
            check_id,
            name,
            "Current base-branch HEAD is unavailable, so merge checkout freshness cannot be proved.",
        )

    successful = tuple(
        run
        for run in context.workflow_runs
        if run.status == "completed" and run.conclusion == "success"
    )
    if not successful:
        return _unknown(
            check_id,
            name,
            "No successful current-head workflow run is available for merge provenance evaluation.",
        )

    fresh = tuple(run for run in successful if _is_fresh_merge_checkout(run, context))
    if fresh:
        fresh_evidence = _run_evidence(check_id, fresh[0], context, ordinal=1)
        return ReviewCheck(
            check_id=check_id,
            name=name,
            category="CI",
            status=ReviewCheckStatus.PASS,
            applicable=True,
            summary="A successful pull-request workflow checked out the current base/head merge result.",
            evidence=(fresh_evidence,),
            findings=(),
            blocking=True,
        )

    incomplete = tuple(run for run in successful if not _has_complete_provenance(run))
    if incomplete:
        return _unknown(
            check_id,
            name,
            (
                f"{len(incomplete)} successful workflow run(s) lack complete pull-request merge "
                "checkout provenance."
            ),
        )

    stale_evidence = tuple(
        _run_evidence(check_id, run, context, ordinal=index)
        for index, run in enumerate(successful, start=1)
    )
    findings = tuple(
        ReviewFinding(
            finding_id=f"{check_id.value}:{index:03d}",
            check_id=check_id,
            severity=ReviewFindingSeverity.WARNING,
            title="Successful CI used a stale or different pull-request merge checkout",
            observation=(
                f"Workflow run {run.run_id} succeeded, but its pull-request event/checkout "
                "provenance does not match the current base/head pair."
            ),
            evidence=(stale_evidence[index - 1],),
            recommendation=(
                "Trigger fresh pull-request CI for the current base/head pair before relying on "
                "automatic approval, or make an explicit human freshness decision."
            ),
            requires_human_decision=True,
        )
        for index, run in enumerate(successful, start=1)
    )
    return ReviewCheck(
        check_id=check_id,
        name=name,
        category="CI",
        status=ReviewCheckStatus.WARNING,
        applicable=True,
        summary=(
            f"{len(successful)} successful workflow run(s) have complete but non-current merge "
            "checkout provenance."
        ),
        evidence=stale_evidence,
        findings=findings,
        blocking=False,
    )


def _has_complete_provenance(run: GitHubWorkflowRun) -> bool:
    return (
        run.event is not None
        and run.pull_request_number is not None
        and run.pull_request_base_sha is not None
        and run.pull_request_head_sha is not None
        and run.checkout is not None
    )


def _expected_merge_refs(pr_number: int) -> frozenset[str]:
    return frozenset(
        {
            f"refs/pull/{pr_number}/merge",
            f"refs/remotes/pull/{pr_number}/merge",
        }
    )


def _is_fresh_merge_checkout(run: GitHubWorkflowRun, context: PullRequestContext) -> bool:
    if not _has_complete_provenance(run) or context.base_branch_head_sha is None:
        return False
    checkout = run.checkout
    assert checkout is not None
    return (
        run.event == "pull_request"
        and run.pull_request_number == context.pr_number
        and run.pull_request_base_sha == context.base_branch_head_sha
        and run.pull_request_head_sha == context.head_sha
        and checkout.ref in _expected_merge_refs(context.pr_number)
        and checkout.base_sha == context.base_branch_head_sha
        and checkout.head_sha == context.head_sha
    )


def _run_evidence(
    check_id: ReviewCheckId,
    run: GitHubWorkflowRun,
    context: PullRequestContext,
    *,
    ordinal: int,
) -> ReviewEvidence:
    checkout = run.checkout
    observed = (
        f"event={run.event};pr={run.pull_request_number};"
        f"base={run.pull_request_base_sha};head={run.pull_request_head_sha};"
        f"ref={None if checkout is None else checkout.ref};"
        f"checkout_sha={None if checkout is None else checkout.sha};"
        f"checkout_base={None if checkout is None else checkout.base_sha};"
        f"checkout_head={None if checkout is None else checkout.head_sha}"
    )
    expected_refs = ",".join(sorted(_expected_merge_refs(context.pr_number)))
    expected = (
        f"event=pull_request;pr={context.pr_number};base={context.base_branch_head_sha};"
        f"head={context.head_sha};ref in [{expected_refs}];"
        f"checkout_base={context.base_branch_head_sha};checkout_head={context.head_sha}"
    )
    return ReviewEvidence(
        evidence_id=f"{check_id.value}:ev:{ordinal:03d}",
        kind=ReviewEvidenceKind.CI_CHECK,
        description=f"Pull-request merge checkout provenance for workflow run {run.run_id}.",
        commit_sha=None if checkout is None else checkout.sha,
        check_id=check_id,
        observed_value=observed,
        expected_value=expected,
    )


def _unknown(check_id: ReviewCheckId, name: str, summary: str) -> ReviewCheck:
    return ReviewCheck(
        check_id=check_id,
        name=name,
        category="CI",
        status=ReviewCheckStatus.UNKNOWN,
        applicable=True,
        summary=summary,
        evidence=(),
        findings=(),
        blocking=True,
    )
