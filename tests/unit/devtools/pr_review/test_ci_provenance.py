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
    evaluate_metadata_checks,
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
    pull_request_base_sha: str | None = "current-base",
    pull_request_head_sha: str | None = "head-sha",
    checkout: bool = True,
    checkout_ref: str = "refs/remotes/pull/42/merge",
    checkout_base_sha: str = "current-base",
    checkout_head_sha: str = "head-sha",
) -> GitHubWorkflowRun:
    return GitHubWorkflowRun(
        run_id=200,
        name="CI",
        head_sha="head-sha",
        status="completed",
        conclusion="success",
        event="pull_request",
        pull_request_number=42,
        pull_request_base_sha=pull_request_base_sha,
        pull_request_head_sha=pull_request_head_sha,
        checkout=(
            GitHubCheckoutProvenance(
                ref=checkout_ref,
                sha="merge-sha",
                base_sha=checkout_base_sha,
                head_sha=checkout_head_sha,
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


def test_ci_003_passes_with_observed_actions_remote_merge_ref() -> None:
    check = evaluate_ci_merge_provenance(_request(), _context(_run()))

    assert check.check_id is ReviewCheckId.CI_003
    assert check.status is ReviewCheckStatus.PASS
    assert check.evidence[0].commit_sha == "merge-sha"
    assert derive_review_decision((check,), ()).decision is ReviewDecision.APPROVE


def test_ci_003_also_accepts_canonical_pull_request_merge_ref() -> None:
    check = evaluate_ci_merge_provenance(
        _request(),
        _context(_run(checkout_ref="refs/pull/42/merge")),
    )

    assert check.status is ReviewCheckStatus.PASS


def test_ci_003_does_not_require_event_snapshot_to_equal_live_checkout() -> None:
    check = evaluate_ci_merge_provenance(
        _request(),
        _context(
            _run(
                pull_request_base_sha="old-base",
                pull_request_head_sha="historical-head-metadata",
                checkout_base_sha="current-base",
                checkout_head_sha="head-sha",
            )
        ),
    )

    assert check.status is ReviewCheckStatus.PASS


def test_ci_003_real_pr93_passes_from_checkout_while_git_005_keeps_snapshot_warning() -> None:
    historical_base = "58d02cfc6e169386834252b4855f04057bb8ba5b"
    current_main = "0f1a9c1bc25272c82fe5264981a2afc82abca7f6"
    head_sha = "94c9bc459cd9123d5a066229b7fdab688c04c54f"
    run = GitHubWorkflowRun(
        run_id=33014164215,
        name="CI",
        head_sha=head_sha,
        status="completed",
        conclusion="success",
        event="pull_request",
        pull_request_number=93,
        pull_request_base_sha=historical_base,
        pull_request_head_sha=head_sha,
        checkout=GitHubCheckoutProvenance(
            ref="refs/remotes/pull/93/merge",
            sha="770e92162f43cd63dc4f20be2531b7c36080b7a6",
            base_sha=current_main,
            head_sha=head_sha,
        ),
    )
    context = PullRequestContext(
        repository="luciusblack2411-create/SCRIPTS",
        pr_number=93,
        title="feat(models): add Switchport Observation v0.1 data model",
        body=None,
        state="open",
        draft=True,
        mergeable=True,
        base_branch="main",
        base_sha=historical_base,
        base_branch_head_sha=current_main,
        head_branch="feat/m14-switchport-observation-data-model",
        head_sha=head_sha,
        changed_files=(),
        commits=(),
        diff_text="",
        workflow_runs=(run,),
    )
    request = ReviewRequest(
        repository="luciusblack2411-create/SCRIPTS",
        pr_number=93,
        objective="Real PR #93 CI provenance regression.",
        expected_components=(ComponentId.CI_TOOLING,),
    )

    ci_check = evaluate_ci_merge_provenance(request, context)
    metadata_checks = evaluate_metadata_checks(request, context)
    git_005 = next(check for check in metadata_checks if check.check_id is ReviewCheckId.GIT_005)

    assert ci_check.status is ReviewCheckStatus.PASS
    assert git_005.status is ReviewCheckStatus.WARNING
    assert git_005.findings[0].requires_human_decision is False


def test_ci_003_rejects_unrelated_checkout_ref() -> None:
    check = evaluate_ci_merge_provenance(
        _request(),
        _context(_run(checkout_ref="refs/heads/main")),
    )

    assert check.status is ReviewCheckStatus.WARNING
    assert check.findings[0].requires_human_decision is True


def test_ci_003_routes_proven_stale_merge_checkout_to_human_review() -> None:
    check = evaluate_ci_merge_provenance(
        _request(),
        _context(
            _run(
                pull_request_base_sha="old-base",
                checkout_base_sha="old-base",
            )
        ),
    )

    assert check.status is ReviewCheckStatus.WARNING
    assert check.findings[0].finding_id == "CI-003:001"
    assert check.findings[0].requires_human_decision is True
    assert (
        derive_review_decision((check,), check.findings).decision
        is ReviewDecision.NEEDS_HUMAN_REVIEW
    )


def test_ci_003_real_pr37_pilot_detects_stale_successful_merge_ci() -> None:
    historical_base = "48f593bd3ec957ad6a1c62050174d451e6de35c6"
    current_main = "e12f11b239c4afb22b299e1b8ac9133328600685"
    head_sha = "e62ce94c6c6d21a6a37cfa69f3e85a73adfdcc2c"
    run = GitHubWorkflowRun(
        run_id=32619758060,
        name="CI",
        head_sha=head_sha,
        status="completed",
        conclusion="success",
        event="pull_request",
        pull_request_number=37,
        pull_request_base_sha=historical_base,
        pull_request_head_sha=head_sha,
        checkout=GitHubCheckoutProvenance(
            ref="refs/remotes/pull/37/merge",
            sha="ff701576af1c19e375a3b7f0a8200825af7c68e4",
            base_sha=historical_base,
            head_sha=head_sha,
        ),
    )
    context = PullRequestContext(
        repository="luciusblack2411-create/SCRIPTS",
        pr_number=37,
        title="feat(reporting): add VlanObservation v0.1 to canonical JSON",
        body=None,
        state="open",
        draft=True,
        mergeable=True,
        base_branch="main",
        base_sha=historical_base,
        base_branch_head_sha=current_main,
        head_branch="feat/reporting-vlan-observation-v0.1",
        head_sha=head_sha,
        changed_files=(),
        commits=(),
        diff_text="",
        workflow_runs=(run,),
    )
    request = ReviewRequest(
        repository="luciusblack2411-create/SCRIPTS",
        pr_number=37,
        objective="Historical PR Review Agent pilot regression.",
        expected_components=(ComponentId.REPORTING, ComponentId.TESTING_FIXTURES),
    )

    check = evaluate_ci_merge_provenance(request, context)

    assert check.status is ReviewCheckStatus.WARNING
    assert check.findings[0].requires_human_decision is True
    assert check.evidence[0].commit_sha == "ff701576af1c19e375a3b7f0a8200825af7c68e4"
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
