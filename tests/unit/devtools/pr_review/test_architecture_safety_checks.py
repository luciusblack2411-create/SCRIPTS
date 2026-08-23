from __future__ import annotations

import pytest

from cisco_assessment.devtools.pr_review import (
    GitHubChangedFile,
    PullRequestContext,
    ReviewCheckId,
    ReviewCheckStatus,
    ReviewDecision,
    derive_review_decision,
    evaluate_architecture_safety_checks,
    extract_added_lines,
)


def _context(diff_text: str, *paths: str) -> PullRequestContext:
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
                deletions=0,
                changes=1,
            )
            for path in paths
        ),
        commits=(),
        diff_text=diff_text,
        workflow_runs=(),
    )


def _single_file_diff(path: str, added_line: str, *, new_line: int = 10) -> str:
    return "\n".join(
        (
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            f"@@ -{new_line},0 +{new_line},1 @@",
            f"+{added_line}",
        )
    )


def _checks_by_id(context: PullRequestContext) -> dict[ReviewCheckId, object]:
    return {check.check_id: check for check in evaluate_architecture_safety_checks(context)}


def test_extract_added_lines_preserves_path_text_and_head_line_number() -> None:
    path = "src/cisco_assessment/parsers/example.py"
    diff_text = "\n".join(
        (
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -7,2 +7,3 @@",
            " context_before",
            "+from cisco_assessment.models import DeviceInfo",
            " context_after",
        )
    )

    added = extract_added_lines(diff_text)

    assert len(added) == 1
    assert added[0].path == path
    assert added[0].line_number == 8
    assert added[0].text == "from cisco_assessment.models import DeviceInfo"


@pytest.mark.parametrize(
    ("path", "added_line", "check_id"),
    (
        (
            "src/cisco_assessment/parsers/example.py",
            "from cisco_assessment.assessment import AssessmentEngine",
            ReviewCheckId.ARCH_001,
        ),
        (
            "src/cisco_assessment/assessment/engine.py",
            "from cisco_assessment.parsers import ParserRegistry",
            ReviewCheckId.ARCH_002,
        ),
        (
            "src/cisco_assessment/assessment/vlan_rules.py",
            "import genie",
            ReviewCheckId.ARCH_003,
        ),
        (
            "src/cisco_assessment/reporting/json_report.py",
            "from cisco_assessment.parsers import ParserRegistry",
            ReviewCheckId.ARCH_004,
        ),
        (
            "src/cisco_assessment/collector/service.py",
            "from cisco_assessment.assessment import AssessmentEngine",
            ReviewCheckId.ARCH_005,
        ),
    ),
)
def test_architecture_boundaries_fail_only_on_new_forbidden_imports(
    path: str,
    added_line: str,
    check_id: ReviewCheckId,
) -> None:
    context = _context(_single_file_diff(path, added_line), path)
    checks = {check.check_id: check for check in evaluate_architecture_safety_checks(context)}

    check = checks[check_id]
    assert check.status is ReviewCheckStatus.FAIL
    assert check.findings[0].finding_id == f"{check_id.value}:001"
    assert check.findings[0].evidence[0].repository_path == path
    assert check.findings[0].evidence[0].line_start == 10
    assert check.findings[0].evidence[0].line_end == 10


def test_parser_allowed_model_import_passes_its_architecture_boundary() -> None:
    path = "src/cisco_assessment/parsers/example.py"
    context = _context(
        _single_file_diff(path, "from cisco_assessment.models import DeviceInfo"),
        path,
    )
    checks = {check.check_id: check for check in evaluate_architecture_safety_checks(context)}

    assert checks[ReviewCheckId.ARCH_001].status is ReviewCheckStatus.PASS
    assert checks[ReviewCheckId.ARCH_002].status is ReviewCheckStatus.NOT_APPLICABLE
    assert checks[ReviewCheckId.ARCH_003].status is ReviewCheckStatus.NOT_APPLICABLE
    assert checks[ReviewCheckId.ARCH_004].status is ReviewCheckStatus.NOT_APPLICABLE
    assert checks[ReviewCheckId.ARCH_005].status is ReviewCheckStatus.NOT_APPLICABLE


def test_safe_001_blocks_state_changing_cli_literal_on_execution_surface() -> None:
    path = "src/cisco_assessment/catalog/mvp.py"
    context = _context(_single_file_diff(path, 'cli_command = "configure terminal"'), path)
    checks = {check.check_id: check for check in evaluate_architecture_safety_checks(context)}

    check = checks[ReviewCheckId.SAFE_001]
    assert check.status is ReviewCheckStatus.FAIL
    assert check.findings[0].finding_id == "SAFE-001:001"
    assert check.findings[0].evidence[0].observed_value == "configure terminal"


def test_safe_001_accepts_show_cli_literal() -> None:
    path = "src/cisco_assessment/catalog/mvp.py"
    context = _context(_single_file_diff(path, 'cli_command = "show vlan brief"'), path)
    checks = {check.check_id: check for check in evaluate_architecture_safety_checks(context)}

    assert checks[ReviewCheckId.SAFE_001].status is ReviewCheckStatus.PASS


def test_safe_001_is_not_applicable_to_parser_observation_literals() -> None:
    path = "src/cisco_assessment/parsers/example.py"
    context = _context(_single_file_diff(path, 'token = "shutdown"'), path)
    checks = {check.check_id: check for check in evaluate_architecture_safety_checks(context)}

    assert checks[ReviewCheckId.SAFE_001].status is ReviewCheckStatus.NOT_APPLICABLE


def test_safe_002_blocks_direct_ssh_import_outside_collector() -> None:
    path = "src/cisco_assessment/runner/service.py"
    context = _context(_single_file_diff(path, "import paramiko"), path)
    checks = {check.check_id: check for check in evaluate_architecture_safety_checks(context)}

    check = checks[ReviewCheckId.SAFE_002]
    assert check.status is ReviewCheckStatus.FAIL
    assert check.findings[0].evidence[0].observed_value == "paramiko"


def test_safe_002_allows_paramiko_inside_collector() -> None:
    path = "src/cisco_assessment/collector/session.py"
    context = _context(_single_file_diff(path, "import paramiko"), path)
    checks = {check.check_id: check for check in evaluate_architecture_safety_checks(context)}

    assert checks[ReviewCheckId.SAFE_002].status is ReviewCheckStatus.NOT_APPLICABLE
    assert checks[ReviewCheckId.ARCH_005].status is ReviewCheckStatus.PASS


def test_blocking_architecture_failure_drives_request_changes() -> None:
    path = "src/cisco_assessment/reporting/json_report.py"
    context = _context(
        _single_file_diff(path, "from cisco_assessment.parsers import ParserRegistry"),
        path,
    )
    checks = evaluate_architecture_safety_checks(context)
    findings = tuple(finding for check in checks for finding in check.findings)

    outcome = derive_review_decision(checks=checks, findings=findings)

    assert outcome.decision is ReviewDecision.REQUEST_CHANGES
