"""Operational request loading, execution, and rendering for PR Review Agent v0.1."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from .github import GitHubReadBackend
from .github_rest import GitHubRestReadBackend
from .models import ReviewReport, ReviewRequest
from .reviewer import review_pr


class ReviewRequestFileError(ValueError):
    """Raised when an operational ReviewRequest file cannot satisfy the strict contract."""


def load_review_request(path: Path) -> ReviewRequest:
    """Load one strict JSON ReviewRequest without inferring missing review scope."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReviewRequestFileError(f"cannot read review request {path}: {exc}") from exc

    try:
        return ReviewRequest.model_validate_json(content)
    except ValidationError as exc:
        raise ReviewRequestFileError(f"invalid review request {path}: {exc}") from exc


def execute_review_request(
    request: ReviewRequest,
    backend: GitHubReadBackend | None = None,
) -> ReviewReport:
    """Execute one advisory review using the production read backend by default."""
    resolved_backend: GitHubReadBackend = backend or GitHubRestReadBackend()
    return review_pr(request, resolved_backend)


def render_review_report_json(report: ReviewReport) -> str:
    """Render the canonical project-owned ReviewReport as deterministic JSON."""
    return report.model_dump_json(indent=2)


def render_review_report_human(report: ReviewReport) -> str:
    """Render a concise human view without replacing canonical structured evidence."""
    current_base_sha = report.base_branch_head_sha or "UNKNOWN"
    components = ", ".join(component.value for component in report.detected_components) or "<none>"
    lines = [
        f"PR #{report.pr_number} — {report.repository}",
        f"Agent: {report.agent_id}",
        f"Decision: {report.decision.value}",
        f"Base: {report.base_branch} snapshot={report.base_sha} current={current_base_sha}",
        f"Head: {report.head_branch} {report.head_sha}",
        f"Objective: {report.objective}",
        f"Detected components: {components}",
        "",
        "Checks:",
    ]

    if report.checks:
        lines.extend(
            f"{check.status.value:<14} {check.check_id.value:<12} {check.summary}"
            for check in report.checks
        )
    else:
        lines.append("<none>")

    lines.extend(("", "Findings:"))
    if report.findings:
        for finding in report.findings:
            human_gate = " human-decision" if finding.requires_human_decision else ""
            lines.append(
                f"[{finding.severity.value}] {finding.finding_id}{human_gate}: {finding.title}"
            )
            lines.append(f"  {finding.observation}")
            if finding.recommendation is not None:
                lines.append(f"  Recommendation: {finding.recommendation}")
    else:
        lines.append("<none>")

    if report.residual_risks:
        lines.extend(("", "Residual risks:"))
        lines.extend(f"- {risk}" for risk in report.residual_risks)

    lines.extend(("", f"Reason: {report.decision_reason}"))
    return "\n".join(lines)
