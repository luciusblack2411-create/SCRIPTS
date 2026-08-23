from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from cisco_assessment.devtools.pr_review import (
    ComponentId,
    GitHubChangedFile,
    GitHubWorkflowRun,
    PullRequestContext,
    ReviewDecision,
    ReviewRequest,
    build_review_report,
    review_pr,
)


class FakeGitHubBackend:
    def __init__(
        self,
        *,
        diff_text: str,
        files: Sequence[Mapping[str, object]],
        mergeable: bool | None = True,
        state: str = "open",
        base_branch: str = "main",
        base_branch_head_sha: str | None = "base-sha",
        workflow_status: str = "completed",
        workflow_conclusion: str | None = "success",
    ) -> None:
        self.diff_text = diff_text
        self.files = files
        self.mergeable = mergeable
        self.state = state
        self.base_branch = base_branch
        self.base_branch_head_sha = base_branch_head_sha
        self.workflow_status = workflow_status
        self.workflow_conclusion = workflow_conclusion

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        del repository
        return {
            "number": pr_number,
            "title": "Synthetic PR",
            "body": "Synthetic body",
            "state": self.state,
            "draft": False,
            "mergeable": self.mergeable,
            "base": {"ref": self.base_branch, "sha": "base-sha"},
            "head": {"ref": "feature", "sha": "head-sha"},
        }

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        del repository
        if self.base_branch_head_sha is None:
            return None
        return {"name": branch, "commit": {"sha": self.base_branch_head_sha}}

    def list_pull_request_files(
        self,
        repository: str,
        pr_number: int,
    ) -> Sequence[Mapping[str, object]]:
        del repository, pr_number
        return self.files

    def list_pull_request_commits(
        self,
        repository: str,
        pr_number: int,
    ) -> Sequence[Mapping[str, object]]:
        del repository, pr_number
        return ()

    def get_pull_request_diff(self, repository: str, pr_number: int) -> str:
        del repository, pr_number
        return self.diff_text

    def list_commit_workflow_runs(
        self,
        repository: str,
        commit_sha: str,
    ) -> Sequence[Mapping[str, object]]:
        del repository
        return (
            {
                "id": 123,
                "name": "CI",
                "head_sha": commit_sha,
                "status": self.workflow_status,
                "conclusion": self.workflow_conclusion,
            },
        )


def _file(path: str) -> Mapping[str, object]:
    return {
        "filename": path,
        "status": "modified",
        "additions": 1,
        "deletions": 0,
        "changes": 1,
    }


def _diff(path: str, added_line: str) -> str:
    return "\n".join(
        (
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -1,0 +1,1 @@",
            f"+{added_line}",
        )
    )


def _request(*components: ComponentId) -> ReviewRequest:
    return ReviewRequest(
        repository="owner/repo",
        pr_number=42,
        objective="Review synthetic change.",
        expected_components=components,
    )


def test_review_pr_builds_approve_report_from_read_only_backend() -> None:
    source = "src/cisco_assessment/devtools/pr_review/example.py"
    test = "tests/unit/devtools/pr_review/test_example.py"
    backend = FakeGitHubBackend(
        diff_text=_diff(source, "VALUE = 1"),
        files=(_file(source), _file(test)),
    )

    report = review_pr(
        _request(ComponentId.CI_TOOLING, ComponentId.TESTING_FIXTURES),
        backend,
    )

    assert report.decision is ReviewDecision.APPROVE
    assert report.repository == "owner/repo"
    assert report.pr_number == 42
    assert report.base_branch_head_sha == "base-sha"
    assert report.head_sha == "head-sha"
    assert report.detected_components == (
        ComponentId.TESTING_FIXTURES,
        ComponentId.CI_TOOLING,
    )
    assert report.contracts_changed == ()


def test_review_pr_allows_base_advancement_as_evidence_backed_residual_risk() -> None:
    source = "src/cisco_assessment/devtools/pr_review/example.py"
    test = "tests/unit/devtools/pr_review/test_example.py"
    backend = FakeGitHubBackend(
        diff_text=_diff(source, "VALUE = 1"),
        files=(_file(source), _file(test)),
        base_branch_head_sha="new-main-head",
    )

    report = review_pr(
        _request(ComponentId.CI_TOOLING, ComponentId.TESTING_FIXTURES),
        backend,
    )

    assert report.decision is ReviewDecision.APPROVE
    assert report.base_sha == "base-sha"
    assert report.base_branch_head_sha == "new-main-head"
    assert any(risk.startswith("GIT-005:001:") for risk in report.residual_risks)


def test_review_pr_blocks_when_current_base_head_is_unavailable() -> None:
    source = "src/cisco_assessment/devtools/pr_review/example.py"
    test = "tests/unit/devtools/pr_review/test_example.py"
    backend = FakeGitHubBackend(
        diff_text=_diff(source, "VALUE = 1"),
        files=(_file(source), _file(test)),
        base_branch_head_sha=None,
    )

    report = review_pr(
        _request(ComponentId.CI_TOOLING, ComponentId.TESTING_FIXTURES),
        backend,
    )

    assert report.decision is ReviewDecision.BLOCKED
    assert report.base_branch_head_sha is None


def test_review_report_requests_changes_for_scope_leak() -> None:
    parser = "src/cisco_assessment/parsers/example.py"
    reporting = "src/cisco_assessment/reporting/example.py"
    context = _context(
        diff_text=_diff(reporting, "VALUE = 1"),
        paths=(parser, reporting),
    )

    report = build_review_report(_request(ComponentId.PARSER), context)

    assert report.decision is ReviewDecision.REQUEST_CHANGES
    assert any(finding.finding_id.startswith("SCOPE-001:") for finding in report.findings)


def test_review_report_requests_changes_for_architecture_violation() -> None:
    path = "src/cisco_assessment/parsers/example.py"
    context = _context(
        diff_text=_diff(path, "from cisco_assessment.assessment import AssessmentEngine"),
        paths=(path,),
    )

    report = build_review_report(_request(ComponentId.PARSER), context)

    assert report.decision is ReviewDecision.REQUEST_CHANGES
    assert any(finding.finding_id.startswith("ARCH-001:") for finding in report.findings)


def test_review_report_routes_stable_contract_rewrite_to_human_review() -> None:
    path = "src/cisco_assessment/catalog/enums.py"
    diff_text = "\n".join(
        (
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -10,1 +10,1 @@",
            '-    VLANS_BRIEF = "vlans.brief"',
            '+    VLANS_BRIEF = "vlans.summary"',
        )
    )
    context = _context(diff_text=diff_text, paths=(path,))

    report = build_review_report(_request(ComponentId.COMMAND_CATALOG), context)

    assert report.decision is ReviewDecision.NEEDS_HUMAN_REVIEW
    assert report.contracts_changed
    assert "VLANS_BRIEF" in report.contracts_changed[0]


def test_review_report_is_blocked_while_required_ci_is_pending() -> None:
    source = "src/cisco_assessment/devtools/pr_review/example.py"
    context = _context(
        diff_text=_diff(source, "VALUE = 1"),
        paths=(source,),
        workflow_status="in_progress",
        workflow_conclusion=None,
    )

    report = build_review_report(_request(ComponentId.CI_TOOLING), context)

    assert report.decision is ReviewDecision.BLOCKED


def test_review_report_rejects_unexpected_base_branch() -> None:
    source = "src/cisco_assessment/devtools/pr_review/example.py"
    context = _context(
        diff_text=_diff(source, "VALUE = 1"),
        paths=(source,),
        base_branch="develop",
    )

    report = build_review_report(_request(ComponentId.CI_TOOLING), context)

    assert report.decision is ReviewDecision.REQUEST_CHANGES
    assert any(finding.finding_id == "GIT-001:001" for finding in report.findings)


def test_review_report_blocks_when_changed_files_have_no_diff() -> None:
    source = "src/cisco_assessment/devtools/pr_review/example.py"
    context = _context(diff_text="", paths=(source,))

    report = build_review_report(_request(ComponentId.CI_TOOLING), context)

    assert report.decision is ReviewDecision.BLOCKED


def test_build_review_report_rejects_mismatched_context_identity() -> None:
    context = _context(
        diff_text=_diff("src/cisco_assessment/devtools/pr_review/example.py", "VALUE = 1"),
        paths=("src/cisco_assessment/devtools/pr_review/example.py",),
        repository="other/repo",
    )

    with pytest.raises(ValueError, match="repository"):
        build_review_report(_request(ComponentId.CI_TOOLING), context)


def _context(
    *,
    diff_text: str,
    paths: tuple[str, ...],
    repository: str = "owner/repo",
    base_branch: str = "main",
    base_branch_head_sha: str | None = "base-sha",
    mergeable: bool | None = True,
    workflow_status: str = "completed",
    workflow_conclusion: str | None = "success",
) -> PullRequestContext:
    return PullRequestContext(
        repository=repository,
        pr_number=42,
        title="Synthetic PR",
        body=None,
        state="open",
        draft=False,
        mergeable=mergeable,
        base_branch=base_branch,
        base_sha="base-sha",
        base_branch_head_sha=base_branch_head_sha,
        head_branch="feature",
        head_sha="head-sha",
        changed_files=tuple(
            GitHubChangedFile(
                path=path,
                status="modified",
                additions=1,
                deletions=0,
                changes=1,
            )
            for path in paths
        ),
        commits=(),
        diff_text=diff_text,
        workflow_runs=(
            GitHubWorkflowRun(
                run_id=123,
                name="CI",
                head_sha="head-sha",
                status=workflow_status,
                conclusion=workflow_conclusion,
            ),
        ),
    )
