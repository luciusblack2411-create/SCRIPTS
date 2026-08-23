from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cisco_assessment.devtools.pr_review import (
    ComponentId,
    ReviewCheck,
    ReviewCheckId,
    ReviewCheckStatus,
    ReviewDecision,
    ReviewFinding,
    ReviewFindingSeverity,
    ReviewReport,
    ReviewRequest,
    ReviewRequestFileError,
    load_review_request,
    render_review_report_human,
    render_review_report_json,
)
from cisco_assessment.devtools.pr_review import cli as review_cli


def _request() -> ReviewRequest:
    return ReviewRequest(
        repository="owner/repo",
        pr_number=37,
        objective="Validate Reporting-only VLAN integration.",
        expected_components=(ComponentId.REPORTING, ComponentId.TESTING_FIXTURES),
        prohibited_components=(ComponentId.COLLECTOR, ComponentId.PARSER),
        expected_contracts=("VlanObservation v0.1",),
        invariants=("Reporting does not parse Cisco CLI.",),
    )


def _report(decision: ReviewDecision = ReviewDecision.APPROVE) -> ReviewReport:
    check = ReviewCheck(
        check_id=ReviewCheckId.GIT_001,
        name="Pull request targets the expected base branch",
        category="GIT",
        status=ReviewCheckStatus.PASS,
        applicable=True,
        summary="Pull request targets the expected base branch.",
        evidence=(),
        findings=(),
        blocking=True,
    )
    finding = ReviewFinding(
        finding_id="GIT-005:001",
        check_id=ReviewCheckId.GIT_005,
        severity=ReviewFindingSeverity.WARNING,
        title="Base branch advanced beyond the PR base snapshot",
        observation="The base snapshot differs from current main.",
        evidence=(),
        recommendation="Require current merge-ref CI provenance.",
        requires_human_decision=decision is ReviewDecision.NEEDS_HUMAN_REVIEW,
    )
    findings = () if decision is ReviewDecision.APPROVE else (finding,)
    return ReviewReport(
        repository="owner/repo",
        pr_number=37,
        base_branch="main",
        base_sha="base-snapshot",
        base_branch_head_sha="current-main",
        head_branch="feature",
        head_sha="head-sha",
        mergeable=True,
        objective="Validate Reporting-only VLAN integration.",
        detected_components=(ComponentId.REPORTING, ComponentId.TESTING_FIXTURES),
        checks=(check,),
        findings=findings,
        contracts_changed=(),
        contracts_verified_stable=(),
        residual_risks=(),
        decision=decision,
        decision_reason=f"Deterministic decision: {decision.value}.",
    )


def test_load_review_request_preserves_explicit_scope(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text(_request().model_dump_json(indent=2), encoding="utf-8")

    loaded = load_review_request(path)

    assert loaded == _request()
    assert loaded.expected_components == (
        ComponentId.REPORTING,
        ComponentId.TESTING_FIXTURES,
    )
    assert loaded.prohibited_components == (ComponentId.COLLECTOR, ComponentId.PARSER)


def test_load_review_request_rejects_uncontracted_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text(
        _request().model_dump_json().removesuffix("}") + ',"infer_scope":true}',
        encoding="utf-8",
    )

    with pytest.raises(ReviewRequestFileError, match="invalid review request"):
        load_review_request(path)


def test_human_renderer_is_concise_and_preserves_decision_context() -> None:
    report = _report(ReviewDecision.NEEDS_HUMAN_REVIEW)

    rendered = render_review_report_human(report)

    assert "PR #37 — owner/repo" in rendered
    assert "Decision: NEEDS_HUMAN_REVIEW" in rendered
    assert "snapshot=base-snapshot current=current-main" in rendered
    assert "REPORTING, TESTING_FIXTURES" in rendered
    assert "PASS           GIT-001" in rendered
    assert "[WARNING] GIT-005:001 human-decision" in rendered
    assert "Require current merge-ref CI provenance." in rendered


def test_json_renderer_round_trips_canonical_review_report() -> None:
    report = _report()

    rendered = render_review_report_json(report)

    assert ReviewReport.model_validate_json(rendered) == report


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (ReviewDecision.APPROVE, 0),
        (ReviewDecision.NEEDS_HUMAN_REVIEW, 2),
        (ReviewDecision.REQUEST_CHANGES, 3),
        (ReviewDecision.BLOCKED, 4),
    ],
)
def test_operational_exit_codes_are_deterministic(
    decision: ReviewDecision,
    expected: int,
) -> None:
    assert review_cli.review_decision_exit_code(decision) == expected


def test_cli_runs_from_explicit_request_and_emits_canonical_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "request.json"
    path.write_text(_request().model_dump_json(indent=2), encoding="utf-8")
    report = _report(ReviewDecision.NEEDS_HUMAN_REVIEW)
    observed: list[ReviewRequest] = []

    def fake_execute(request: ReviewRequest) -> ReviewReport:
        observed.append(request)
        return report

    monkeypatch.setattr(review_cli, "execute_review_request", fake_execute)

    result = CliRunner().invoke(
        review_cli.app,
        ["run", str(path), "--output", "json"],
    )

    assert result.exit_code == 2
    assert observed == [_request()]
    assert '"decision": "NEEDS_HUMAN_REVIEW"' in result.stdout
    assert ReviewReport.model_validate_json(result.stdout) == report


def test_cli_invalid_request_fails_before_any_github_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "request.json"
    path.write_text("{}", encoding="utf-8")
    executed = False

    def fail_if_executed(request: ReviewRequest) -> ReviewReport:
        nonlocal executed
        executed = True
        return _report()

    monkeypatch.setattr(review_cli, "execute_review_request", fail_if_executed)

    result = CliRunner().invoke(review_cli.app, ["run", str(path)])

    assert result.exit_code == 4
    assert executed is False
    assert "ERROR: invalid review request" in result.stderr
