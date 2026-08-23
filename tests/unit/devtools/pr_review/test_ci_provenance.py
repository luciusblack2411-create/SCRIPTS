from __future__ import annotations

from cisco_assessment.devtools.pr_review import (
    ComponentId,
    GitHubCheckoutProvenance,
    GitHubWorkflowRun,
    PullRequestContext,
    ReviewCheckId,
    ReviewCheckStatus,
    ReviewDecision,
    ReviewRequest,
    derive_review_decision,
    evaluate_ci_merge_provenance,
)


def _request(*, require_ci_success: bool = True) -> ReviewRequest:
    return ReviewRequest(
        repository="owner/repo",
        pr_number=42,
        objective="Review CI provenance.",
        expected_components=(ComponentId.CI_TOOLING,),
        require_ci_success=require_ci_success,
    )


def _run(
    *,
    base_sha: str = "current-base",
    head_sha: str = "head-sha",
    checkout: bool = True,
) -> GitHubWorkflowRun:
    return GitHubWorkflowRun(
        run_id=200,
        name="CI",
        head_sha="head-sha",
        status="completed",
        conclusion="success",
        event="pull_request",
        pull_request_number=42,
        pull_request_base_sha=base_sha,
        pull_request_head_sha=head_sha,
        checkout=(
            GitHubCheckoutProvenance(
                ref="refs/pull/42/merge",
                sha="merge-sha",
                base_sha=base_sha,
                head_sha=head_sha,
            )
            if checkout
            else None
        ),
    )


def _context(
    run: GitHubWorkflowRun,
    *,
    base_branch_head_sha: str | None = "current-base",
) -> PullRequestContext:
    return PullRequestContext(
        repository="owner/repo",
        pr_number=42,
        title="Synthetic PR",
        body=None,
        state="open",
        draft=False,
        mergeable=True,
        base_branch="main",
        base_sha="old-base",
        base_branch_head_sha=base_branch_head_sha,
        head_branch="feature",
        head_sha="head-sha",
        changed_files=(),
        commits=(),
        diff_text="",
        workflow_runs=(run,),
    )


def test_ci_003_passes_with_exact_current_merge_checkout_provenance() -> None:
    check = evaluate_ci_merge_provenance(_request(), _context(_run()))

    assert check.check_id is ReviewCheckId.CI_003
    assert check.status is ReviewCheckStatus.PASS
    assert check.evidence[0].commit_sha == "merge-sha"
    assert derive_review_decision((check,), ()).decision is ReviewDecision.APPROVE


def test_ci_003_routes_proven_stale_merge_checkout_to_human_review() -> None:
    check = evaluate_ci_merge_provenance(
        _request(),
        _context(_run(base_sha="old-base")),
    )

    assert check.status is ReviewCheckStatus.WARNING
    assert check.findings[0].finding_id == "CI-003:001"
    assert check.findings[0].requires_human_decision is True
    assert (
        derive_review_decision((check,), check.findings).decision
        is ReviewDecision.NEEDS_HUMAN_REVIEW
    )


def test_ci_003_blocks_when_successful_run_lacks_checkout_provenance() -> None:
    check = evaluate_ci_merge_provenance(
        _request(),
        _context(_run(checkout=False)),
    )

    assert check.status is ReviewCheckStatus.UNKNOWN
    assert check.blocking is True
    assert derive_review_decision((check,), ()).decision is ReviewDecision.BLOCKED


def test_ci_003_blocks_when_current_base_head_is_unavailable() -> None:
    check = evaluate_ci_merge_provenance(
        _request(),
        _context(_run(), base_branch_head_sha=None),
    )

    assert check.status is ReviewCheckStatus.UNKNOWN
    assert derive_review_decision((check,), ()).decision is ReviewDecision.BLOCKED


def test_ci_003_is_not_applicable_when_ci_success_is_not_required() -> None:
    check = evaluate_ci_merge_provenance(
        _request(require_ci_success=False),
        _context(_run()),
    )

    assert check.status is ReviewCheckStatus.NOT_APPLICABLE
    assert check.applicable is False
