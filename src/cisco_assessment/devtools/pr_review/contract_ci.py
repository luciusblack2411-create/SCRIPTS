"""Stable-contract, regression-quality, and CI checks for PR Review Agent v0.1."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cisco_assessment.devtools.pr_review.check_ids import ReviewCheckId
from cisco_assessment.devtools.pr_review.enums import (
    ReviewCheckStatus,
    ReviewEvidenceKind,
    ReviewFindingSeverity,
)
from cisco_assessment.devtools.pr_review.github import PullRequestContext
from cisco_assessment.devtools.pr_review.models import (
    ReviewCheck,
    ReviewEvidence,
    ReviewFinding,
    ReviewRequest,
)


@dataclass(frozen=True, slots=True)
class DiffRemovedLine:
    """One removed line extracted from the base side of a unified diff."""

    path: str
    line_number: int
    text: str


_HUNK_RE = re.compile(r"^@@\s+-(?P<old>\d+)(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@")
_ENUM_MEMBER_RE = re.compile(r'^    [A-Z][A-Z0-9_]+\s*=\s*["\'][^"\']+["\']\s*$')
_RULE_ID_RE = re.compile(r'\brule_id\s*=\s*["\'][^"\']+["\']')
_MODEL_FIELD_RE = re.compile(r"^    [a-z][a-z0-9_]*:\s*[^=]+(?:=.*)?$")
_STABLE_ENUM_PATHS = frozenset(
    {
        "src/cisco_assessment/catalog/enums.py",
        "src/cisco_assessment/runner/plan.py",
        "src/cisco_assessment/devtools/pr_review/check_ids.py",
    }
)


def extract_removed_lines(diff_text: str) -> tuple[DiffRemovedLine, ...]:
    """Extract removed lines and their base-side source line numbers from a unified diff."""
    current_path: str | None = None
    old_line_number: int | None = None
    removed: list[DiffRemovedLine] = []

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("--- "):
            candidate = raw_line[4:]
            current_path = candidate.removeprefix("a/")
            if current_path == "/dev/null":
                current_path = None
            old_line_number = None
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match is not None:
            old_line_number = int(hunk_match.group("old"))
            continue

        if current_path is None or old_line_number is None:
            continue

        if raw_line.startswith("-") and not raw_line.startswith("---"):
            removed.append(
                DiffRemovedLine(
                    path=current_path,
                    line_number=old_line_number,
                    text=raw_line[1:],
                )
            )
            old_line_number += 1
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            continue

        if raw_line.startswith(" ") or raw_line == "":
            old_line_number += 1

    return tuple(removed)


def evaluate_contract_quality_ci_checks(
    request: ReviewRequest,
    context: PullRequestContext,
) -> tuple[ReviewCheck, ...]:
    """Evaluate stable-contract review, test accompaniment, and current-head CI state."""
    removed_lines = extract_removed_lines(context.diff_text)
    return (
        _evaluate_stable_ids(removed_lines),
        _evaluate_public_model_fields(removed_lines),
        _evaluate_test_accompaniment(context),
        _evaluate_ci_presence(request, context),
        _evaluate_ci_success(request, context),
    )


def _evaluate_stable_ids(removed_lines: tuple[DiffRemovedLine, ...]) -> ReviewCheck:
    check_id = ReviewCheckId.CONTRACT_001
    candidates = tuple(line for line in removed_lines if _is_stable_id_line(line))
    if not candidates:
        return _pass(
            check_id=check_id,
            name="Stable public identifiers are not removed or rewritten",
            category="CONTRACT",
            summary="No removed stable-ID declaration was detected in the pull-request diff.",
            blocking=False,
        )

    invariant = (
        "CommandId, ParserId, NormalizedModelId, RuleId, AssessmentPlanId, and review-check IDs "
        "are stable contracts; removals or value rewrites require explicit human review."
    )
    evidence = tuple(
        _removed_line_evidence(check_id, index, line, invariant)
        for index, line in enumerate(candidates, start=1)
    )
    findings = tuple(
        ReviewFinding(
            finding_id=f"{check_id.value}:{index:03d}",
            check_id=check_id,
            severity=ReviewFindingSeverity.WARNING,
            title="Stable identifier declaration was removed or rewritten",
            observation=(
                f"{line.path}:{line.line_number} removes a declaration treated as a stable public ID."
            ),
            violated_invariant=invariant,
            evidence=(evidence[index - 1],),
            recommendation="Confirm the contract change explicitly before integration.",
            requires_human_decision=True,
        )
        for index, line in enumerate(candidates, start=1)
    )
    return ReviewCheck(
        check_id=check_id,
        name="Stable public identifiers are not removed or rewritten",
        category="CONTRACT",
        status=ReviewCheckStatus.WARNING,
        applicable=True,
        summary=f"{len(candidates)} stable-ID declaration change(s) require human review.",
        evidence=evidence,
        findings=findings,
        blocking=False,
    )


def _evaluate_public_model_fields(removed_lines: tuple[DiffRemovedLine, ...]) -> ReviewCheck:
    check_id = ReviewCheckId.CONTRACT_002
    candidates = tuple(
        line
        for line in removed_lines
        if line.path.startswith("src/cisco_assessment/models/")
        and line.path != "src/cisco_assessment/models/raw.py"
        and _MODEL_FIELD_RE.match(line.text) is not None
    )
    if not candidates:
        return _pass(
            check_id=check_id,
            name="Normalized-model public field paths remain stable",
            category="CONTRACT",
            summary="No removed normalized-model field declaration was detected.",
            blocking=False,
        )

    invariant = "Public normalized-model field paths are stable contracts; breaking changes must be explicit."
    evidence = tuple(
        _removed_line_evidence(check_id, index, line, invariant)
        for index, line in enumerate(candidates, start=1)
    )
    findings = tuple(
        ReviewFinding(
            finding_id=f"{check_id.value}:{index:03d}",
            check_id=check_id,
            severity=ReviewFindingSeverity.WARNING,
            title="Normalized-model field declaration was removed or rewritten",
            observation=(
                f"{line.path}:{line.line_number} removes a class-level annotated field declaration."
            ),
            violated_invariant=invariant,
            evidence=(evidence[index - 1],),
            recommendation="Confirm field-path compatibility or document the breaking contract change.",
            requires_human_decision=True,
        )
        for index, line in enumerate(candidates, start=1)
    )
    return ReviewCheck(
        check_id=check_id,
        name="Normalized-model public field paths remain stable",
        category="CONTRACT",
        status=ReviewCheckStatus.WARNING,
        applicable=True,
        summary=f"{len(candidates)} normalized-model field change(s) require human review.",
        evidence=evidence,
        findings=findings,
        blocking=False,
    )


def _evaluate_test_accompaniment(context: PullRequestContext) -> ReviewCheck:
    check_id = ReviewCheckId.QUALITY_001
    source_paths = tuple(
        item.path
        for item in context.changed_files
        if item.path.startswith("src/cisco_assessment/") and item.path.endswith(".py")
    )
    if not source_paths:
        return _not_applicable(
            check_id=check_id,
            name="Source changes are accompanied by tests",
            category="QUALITY",
            summary="No Python source file is changed by this pull request.",
            blocking=False,
        )

    test_paths = tuple(item.path for item in context.changed_files if item.path.startswith("tests/"))
    if test_paths:
        return _pass(
            check_id=check_id,
            name="Source changes are accompanied by tests",
            category="QUALITY",
            summary="At least one test file accompanies the Python source changes.",
            blocking=False,
        )

    evidence = tuple(
        ReviewEvidence(
            evidence_id=f"{check_id.value}:ev:{index:03d}",
            kind=ReviewEvidenceKind.FILE,
            description="Changed Python source file without an accompanying changed test file.",
            repository_path=path,
            check_id=check_id,
            observed_value="source changed",
            expected_value="review whether regression/unit tests are required",
        )
        for index, path in enumerate(sorted(source_paths), start=1)
    )
    finding = ReviewFinding(
        finding_id=f"{check_id.value}:001",
        check_id=check_id,
        severity=ReviewFindingSeverity.WARNING,
        title="Python source changed without a changed test file",
        observation="The pull request changes Python source but no path under tests/.",
        evidence=evidence,
        recommendation="Confirm that existing tests are sufficient or add focused regression/unit coverage.",
    )
    return ReviewCheck(
        check_id=check_id,
        name="Source changes are accompanied by tests",
        category="QUALITY",
        status=ReviewCheckStatus.WARNING,
        applicable=True,
        summary="Source changes have no accompanying changed test file.",
        evidence=evidence,
        findings=(finding,),
        blocking=False,
    )


def _evaluate_ci_presence(request: ReviewRequest, context: PullRequestContext) -> ReviewCheck:
    check_id = ReviewCheckId.CI_001
    if not request.require_ci_success:
        return _not_applicable(
            check_id=check_id,
            name="Current-head CI evidence is available",
            category="CI",
            summary="The review request does not require CI success.",
            blocking=True,
        )
    if context.workflow_runs:
        return _pass(
            check_id=check_id,
            name="Current-head CI evidence is available",
            category="CI",
            summary="At least one workflow run is available for the current PR head SHA.",
            blocking=True,
        )
    return ReviewCheck(
        check_id=check_id,
        name="Current-head CI evidence is available",
        category="CI",
        status=ReviewCheckStatus.UNKNOWN,
        applicable=True,
        summary="No workflow run is available for the current PR head SHA.",
        evidence=(),
        findings=(),
        blocking=True,
    )


def _evaluate_ci_success(request: ReviewRequest, context: PullRequestContext) -> ReviewCheck:
    check_id = ReviewCheckId.CI_002
    if not request.require_ci_success:
        return _not_applicable(
            check_id=check_id,
            name="Required current-head CI completed successfully",
            category="CI",
            summary="The review request does not require CI success.",
            blocking=True,
        )
    if not context.workflow_runs:
        return ReviewCheck(
            check_id=check_id,
            name="Required current-head CI completed successfully",
            category="CI",
            status=ReviewCheckStatus.UNKNOWN,
            applicable=True,
            summary="CI success cannot be established because no current-head workflow run is available.",
            evidence=(),
            findings=(),
            blocking=True,
        )

    pending = tuple(run for run in context.workflow_runs if run.status != "completed")
    failed = tuple(
        run
        for run in context.workflow_runs
        if run.status == "completed" and run.conclusion != "success"
    )
    if failed:
        evidence = tuple(
            ReviewEvidence(
                evidence_id=f"{check_id.value}:ev:{index:03d}",
                kind=ReviewEvidenceKind.CI_CHECK,
                description=f"Workflow run {run.run_id} ({run.name}) did not succeed.",
                commit_sha=context.head_sha,
                check_id=check_id,
                observed_value=run.conclusion or "none",
                expected_value="success",
            )
            for index, run in enumerate(failed, start=1)
        )
        findings = tuple(
            ReviewFinding(
                finding_id=f"{check_id.value}:{index:03d}",
                check_id=check_id,
                severity=ReviewFindingSeverity.BLOCKING,
                title="Required CI workflow did not succeed",
                observation=f"Workflow run {run.run_id} ({run.name}) concluded {run.conclusion!r}.",
                evidence=(evidence[index - 1],),
                recommendation="Correct the failing CI checks before integration.",
            )
            for index, run in enumerate(failed, start=1)
        )
        return ReviewCheck(
            check_id=check_id,
            name="Required current-head CI completed successfully",
            category="CI",
            status=ReviewCheckStatus.FAIL,
            applicable=True,
            summary=f"{len(failed)} current-head workflow run(s) did not succeed.",
            evidence=evidence,
            findings=findings,
            blocking=True,
        )

    if pending:
        return ReviewCheck(
            check_id=check_id,
            name="Required current-head CI completed successfully",
            category="CI",
            status=ReviewCheckStatus.UNKNOWN,
            applicable=True,
            summary=f"{len(pending)} current-head workflow run(s) are not completed yet.",
            evidence=(),
            findings=(),
            blocking=True,
        )

    return _pass(
        check_id=check_id,
        name="Required current-head CI completed successfully",
        category="CI",
        summary="All available current-head workflow runs completed successfully.",
        blocking=True,
    )


def _is_stable_id_line(line: DiffRemovedLine) -> bool:
    if line.path in _STABLE_ENUM_PATHS and _ENUM_MEMBER_RE.match(line.text) is not None:
        return True
    return (
        line.path.startswith("src/cisco_assessment/assessment/")
        and line.path.endswith("_rules.py")
        and _RULE_ID_RE.search(line.text) is not None
    )


def _removed_line_evidence(
    check_id: ReviewCheckId,
    ordinal: int,
    line: DiffRemovedLine,
    invariant: str,
) -> ReviewEvidence:
    return ReviewEvidence(
        evidence_id=f"{check_id.value}:ev:{ordinal:03d}",
        kind=ReviewEvidenceKind.SOURCE_LINE,
        description="Removed base-side source line matches a protected public-contract pattern.",
        repository_path=line.path,
        line_start=line.line_number,
        line_end=line.line_number,
        check_id=check_id,
        observed_value=line.text.strip(),
        expected_value=invariant,
    )


def _pass(
    *, check_id: ReviewCheckId, name: str, category: str, summary: str, blocking: bool
) -> ReviewCheck:
    return ReviewCheck(
        check_id=check_id,
        name=name,
        category=category,
        status=ReviewCheckStatus.PASS,
        applicable=True,
        summary=summary,
        evidence=(),
        findings=(),
        blocking=blocking,
    )


def _not_applicable(
    *, check_id: ReviewCheckId, name: str, category: str, summary: str, blocking: bool
) -> ReviewCheck:
    return ReviewCheck(
        check_id=check_id,
        name=name,
        category=category,
        status=ReviewCheckStatus.NOT_APPLICABLE,
        applicable=False,
        summary=summary,
        evidence=(),
        findings=(),
        blocking=blocking,
    )
