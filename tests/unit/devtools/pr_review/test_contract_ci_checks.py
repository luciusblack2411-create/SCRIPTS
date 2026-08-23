from __future__ import annotations

from cisco_assessment.devtools.pr_review import (
    ComponentId,
    GitHubChangedFile,
    GitHubWorkflowRun,
    PullRequestContext,
    ReviewCheckId,
    ReviewCheckStatus,
    ReviewDecision,
    ReviewRequest,
    derive_review_decision,
)
from cisco_assessment.devtools.pr_review.contract_ci import (
    evaluate_contract_quality_ci_checks,
    extract_removed_lines,
)


def _context(
    diff_text: str,
    *paths: str,
    workflow_runs: tuple[GitHubWorkflowRun, ...] = (),
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
        base_sha="base-sha",
        head_branch="feature",
        head_sha="head-sha",
        changed_files=tuple(
            GitHubChangedFile(
                path=path,
                status="modified",
                additions=1,
                deletions=1,
                changes=2,
            )
            for path in paths
        ),
        commits=(),
        diff_text=diff_text,
        workflow_runs=workflow_runs,
    )


def _request(*, require_ci_success: bool = True) -> ReviewRequest:
    return ReviewRequest(
        repository="owner/repo",
        pr_number=42,
        objective="Synthetic review.",
        expected_components=(ComponentId.CI_TOOLING,),
        require_ci_success=require_ci_success,
    )


def _replacement_diff(path: str, old_line: str, new_line: str, *, old_start: int = 10) -> str:
    return "\n".join(
        (
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            f"@@ -{old_start},1 +{old_start},1 @@",
            f"-{old_line}",
            f"+{new_line}",
        )
    )


def test_extract_removed_lines_preserves_base_side_line_number() -> None:
    path = "src/cisco_assessment/catalog/enums.py"
    removed = extract_removed_lines(
        _replacement_diff(
            path,
            '    VLANS_BRIEF = "vlans.brief"',
            '    VLANS = "vlans.brief"',
            old_start=18,
        )
    )

    assert len(removed) == 1
    assert removed[0].path == path
    assert removed[0].line_number == 18
    assert removed[0].text == '    VLANS_BRIEF = "vlans.brief"'


def test_contract_001_routes_stable_id_rewrite_to_human_review() -> None:
    path = "src/cisco_assessment/catalog/enums.py"
    context = _context(
        _replacement_diff(
            path,
            '    VLANS_BRIEF = "vlans.brief"',
            '    VLANS_BRIEF = "vlans.summary"',
        ),
        path,
    )

    checks = evaluate_contract_quality_ci_checks(
        _request(require_ci_success=False),
        context,
    )
    contract = checks[0]
    findings = tuple(finding for check in checks for finding in check.findings)

    assert contract.check_id is ReviewCheckId.CONTRACT_001
    assert contract.status is ReviewCheckStatus.WARNING
    assert contract.findings[0].requires_human_decision is True
    assert contract.findings[0].evidence[0].repository_path == path
    assert derive_review_decision(checks, findings).decision is ReviewDecision.NEEDS_HUMAN_REVIEW


def test_contract_001_detects_rule_id_rewrite() -> None:
    path = "src/cisco_assessment/assessment/vlan_observation_rules.py"
    context = _context(
        _replacement_diff(path, '        rule_id="VLAN-001",', '        rule_id="VLAN-010",'),
        path,
    )

    contract = evaluate_contract_quality_ci_checks(
        _request(require_ci_success=False),
        context,
    )[0]

    assert contract.status is ReviewCheckStatus.WARNING
    assert contract.findings[0].requires_human_decision is True


def test_contract_002_routes_normalized_field_removal_to_human_review() -> None:
    path = "src/cisco_assessment/models/vlan.py"
    context = _context(
        _replacement_diff(path, "    vlan_id: int", "    identifier: int"),
        path,
    )

    checks = evaluate_contract_quality_ci_checks(
        _request(require_ci_success=False),
        context,
    )

    contract = checks[1]
    assert contract.check_id is ReviewCheckId.CONTRACT_002
    assert contract.status is ReviewCheckStatus.WARNING
    assert contract.findings[0].requires_human_decision is True


def test_quality_001_warns_when_source_changes_without_tests() -> None:
    path = "src/cisco_assessment/devtools/pr_review/decision.py"
    context = _context("", path)

    quality = evaluate_contract_quality_ci_checks(
        _request(require_ci_success=False),
        context,
    )[2]

    assert quality.check_id is ReviewCheckId.QUALITY_001
    assert quality.status is ReviewCheckStatus.WARNING
    assert quality.blocking is False


def test_quality_001_passes_when_tests_accompany_source_changes() -> None:
    context = _context(
        "",
        "src/cisco_assessment/devtools/pr_review/decision.py",
        "tests/unit/devtools/pr_review/test_decision.py",
    )

    quality = evaluate_contract_quality_ci_checks(
        _request(require_ci_success=False),
        context,
    )[2]

    assert quality.status is ReviewCheckStatus.PASS


def test_ci_checks_block_when_required_current_head_evidence_is_missing() -> None:
    checks = evaluate_contract_quality_ci_checks(_request(), _context(""))

    assert checks[3].status is ReviewCheckStatus.UNKNOWN
    assert checks[4].status is ReviewCheckStatus.UNKNOWN
    assert derive_review_decision(checks, ()).decision is ReviewDecision.BLOCKED


def test_ci_success_passes_only_when_all_current_head_runs_succeed() -> None:
    run = GitHubWorkflowRun(
        run_id=100,
        name="CI",
        head_sha="head-sha",
        status="completed",
        conclusion="success",
    )
    checks = evaluate_contract_quality_ci_checks(
        _request(),
        _context("", workflow_runs=(run,)),
    )

    assert checks[3].status is ReviewCheckStatus.PASS
    assert checks[4].status is ReviewCheckStatus.PASS


def test_ci_failure_is_blocking_and_evidence_backed() -> None:
    run = GitHubWorkflowRun(
        run_id=101,
        name="CI",
        head_sha="head-sha",
        status="completed",
        conclusion="failure",
    )
    checks = evaluate_contract_quality_ci_checks(
        _request(),
        _context("", workflow_runs=(run,)),
    )
    ci_success = checks[4]

    assert ci_success.status is ReviewCheckStatus.FAIL
    assert ci_success.findings[0].finding_id == "CI-002:001"
    assert ci_success.findings[0].evidence[0].commit_sha == "head-sha"
    assert derive_review_decision(checks, ci_success.findings).decision is ReviewDecision.REQUEST_CHANGES


def test_ci_pending_is_blocking_unknown_not_failure() -> None:
    run = GitHubWorkflowRun(
        run_id=102,
        name="CI",
        head_sha="head-sha",
        status="in_progress",
        conclusion=None,
    )
    checks = evaluate_contract_quality_ci_checks(
        _request(),
        _context("", workflow_runs=(run,)),
    )

    assert checks[4].status is ReviewCheckStatus.UNKNOWN
    assert derive_review_decision(checks, ()).decision is ReviewDecision.BLOCKED
