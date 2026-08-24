from __future__ import annotations

from cisco_assessment.devtools.pr_review import (
    ComponentId,
    GitHubChangedFile,
    PullRequestContext,
    ReviewCheckId,
    ReviewCheckStatus,
    ReviewDecision,
    ReviewRequest,
    derive_review_decision,
)
from cisco_assessment.devtools.pr_review.scope import (
    classify_changed_files,
    classify_changed_path,
    detected_components,
    evaluate_scope_checks,
)


def _context(*paths: str) -> PullRequestContext:
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
        diff_text="",
        workflow_runs=(),
    )


def test_classify_changed_path_uses_repository_boundaries() -> None:
    assert classify_changed_path("src/cisco_assessment/collector/service.py") is ComponentId.COLLECTOR
    assert (
        classify_changed_path("src/cisco_assessment/catalog/mvp.py")
        is ComponentId.COMMAND_CATALOG
    )
    assert classify_changed_path("src/cisco_assessment/models/raw.py") is ComponentId.RAW_MODELS
    assert (
        classify_changed_path("src/cisco_assessment/models/vlan.py")
        is ComponentId.NORMALIZED_MODELS
    )
    assert classify_changed_path("src/cisco_assessment/parsers/vlan.py") is ComponentId.PARSER
    assert (
        classify_changed_path("src/cisco_assessment/assessment/vlan_rules.py")
        is ComponentId.RULES
    )
    assert (
        classify_changed_path("src/cisco_assessment/assessment/engine.py")
        is ComponentId.ENGINE
    )
    assert (
        classify_changed_path("src/cisco_assessment/reporting/json_report.py")
        is ComponentId.REPORTING
    )
    assert (
        classify_changed_path("src/cisco_assessment/runner/plan.py")
        is ComponentId.ASSESSMENT_PLAN
    )
    assert classify_changed_path("src/cisco_assessment/runner/service.py") is ComponentId.RUNNER_CLI
    assert classify_changed_path("src/cisco_assessment/cli.py") is ComponentId.RUNNER_CLI
    assert classify_changed_path("tests/unit/parsers/test_vlan.py") is ComponentId.TESTING_FIXTURES
    assert classify_changed_path(".github/workflows/ci.yml") is ComponentId.CI_TOOLING
    assert (
        classify_changed_path("src/cisco_assessment/devtools/pr_review/scope.py")
        is ComponentId.CI_TOOLING
    )
    assert classify_changed_path("README.md") is ComponentId.DOCUMENTATION
    assert classify_changed_path("unclassified/path.txt") is ComponentId.UNKNOWN


def test_classification_and_detected_components_are_deterministic() -> None:
    context = _context(
        "tests/unit/parsers/test_vlan.py",
        "src/cisco_assessment/parsers/vlan.py",
        "src/cisco_assessment/reporting/json_report.py",
    )

    classifications = classify_changed_files(context.changed_files)

    assert [item.path for item in classifications] == sorted(
        item.path for item in context.changed_files
    )
    assert detected_components(context) == (
        ComponentId.PARSER,
        ComponentId.TESTING_FIXTURES,
        ComponentId.REPORTING,
    )


def test_scope_001_passes_when_all_changed_files_are_authorized() -> None:
    request = ReviewRequest(
        repository="owner/repo",
        pr_number=42,
        objective="Parser-only implementation with tests.",
        expected_components=(ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
    )
    context = _context(
        "src/cisco_assessment/parsers/vlan.py",
        "tests/unit/parsers/test_vlan.py",
    )

    scope_001, scope_002 = evaluate_scope_checks(request, context)

    assert scope_001.check_id is ReviewCheckId.SCOPE_001
    assert scope_001.status is ReviewCheckStatus.PASS
    assert scope_001.findings == ()
    assert scope_002.status is ReviewCheckStatus.NOT_APPLICABLE


def test_scope_001_blocks_unexpected_component_with_file_evidence() -> None:
    request = ReviewRequest(
        repository="owner/repo",
        pr_number=42,
        objective="Parser-only implementation with tests.",
        expected_components=(ComponentId.PARSER, ComponentId.TESTING_FIXTURES),
    )
    context = _context(
        "src/cisco_assessment/parsers/vlan.py",
        "src/cisco_assessment/reporting/json_report.py",
    )

    scope_001, _ = evaluate_scope_checks(request, context)

    assert scope_001.status is ReviewCheckStatus.FAIL
    assert [finding.finding_id for finding in scope_001.findings] == ["SCOPE-001:001"]
    assert scope_001.findings[0].evidence[0].repository_path == (
        "src/cisco_assessment/reporting/json_report.py"
    )

    outcome = derive_review_decision(
        checks=(scope_001,),
        findings=scope_001.findings,
    )
    assert outcome.decision is ReviewDecision.REQUEST_CHANGES


def test_scope_001_does_not_ignore_unknown_paths() -> None:
    request = ReviewRequest(
        repository="owner/repo",
        pr_number=42,
        objective="Parser-only implementation.",
        expected_components=(ComponentId.PARSER,),
    )

    scope_001, _ = evaluate_scope_checks(request, _context("unexpected/file.txt"))

    assert scope_001.status is ReviewCheckStatus.FAIL
    assert scope_001.findings[0].evidence[0].observed_value == ComponentId.UNKNOWN.value


def test_scope_002_blocks_explicitly_prohibited_components() -> None:
    request = ReviewRequest(
        repository="owner/repo",
        pr_number=42,
        objective="Testing-only regression lock.",
        expected_components=(ComponentId.TESTING_FIXTURES,),
        prohibited_components=(ComponentId.PARSER, ComponentId.REPORTING),
    )
    context = _context(
        "tests/unit/parsers/test_vlan.py",
        "src/cisco_assessment/parsers/vlan.py",
    )

    _, scope_002 = evaluate_scope_checks(request, context)

    assert scope_002.status is ReviewCheckStatus.FAIL
    assert [finding.finding_id for finding in scope_002.findings] == ["SCOPE-002:001"]
    assert scope_002.findings[0].evidence[0].repository_path == (
        "src/cisco_assessment/parsers/vlan.py"
    )


def test_scope_findings_are_ordered_by_repository_path() -> None:
    request = ReviewRequest(
        repository="owner/repo",
        pr_number=42,
        objective="Parser-only implementation.",
        expected_components=(ComponentId.PARSER,),
    )
    context = _context(
        "z-unknown.txt",
        "src/cisco_assessment/reporting/json_report.py",
        "a-unknown.txt",
    )

    scope_001, _ = evaluate_scope_checks(request, context)

    assert [finding.evidence[0].repository_path for finding in scope_001.findings] == [
        "a-unknown.txt",
        "src/cisco_assessment/reporting/json_report.py",
        "z-unknown.txt",
    ]
    assert [finding.finding_id for finding in scope_001.findings] == [
        "SCOPE-001:001",
        "SCOPE-001:002",
        "SCOPE-001:003",
    ]
