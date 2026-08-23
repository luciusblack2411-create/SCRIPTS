"""Deterministic changed-file classification and approved-scope checks."""

from __future__ import annotations

import collections.abc
import pathlib

from .check_ids import ReviewCheckId
from .enums import ComponentId, ReviewCheckStatus, ReviewEvidenceKind, ReviewFindingSeverity
from .github import GitHubChangedFile, PullRequestContext
from .models import ReviewCheck, ReviewEvidence, ReviewFinding, ReviewRequest


_COMPONENT_ORDER: tuple[ComponentId, ...] = tuple(ComponentId)


class ChangedFileClassification:
    """Deterministic classification of one GitHub changed path."""

    __slots__ = ("component", "path")

    def __init__(self, path: str, component: ComponentId) -> None:
        self.path = path
        self.component = component

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ChangedFileClassification):
            return NotImplemented
        return self.path == other.path and self.component is other.component

    def __repr__(self) -> str:
        return f"ChangedFileClassification(path={self.path!r}, component={self.component!r})"


def classify_changed_path(path: str) -> ComponentId:
    """Classify a repository path without inspecting or inferring file contents."""
    pure_path = pathlib.PurePosixPath(path)
    parts = pure_path.parts

    if not parts:
        return ComponentId.UNKNOWN

    if parts[0] == "tests":
        return ComponentId.TESTING_FIXTURES
    if parts[0] == ".github" or path == "pyproject.toml":
        return ComponentId.CI_TOOLING
    if path.startswith("src/cisco_assessment/devtools/"):
        return ComponentId.CI_TOOLING
    if parts[0] == "docs" or path == "README.md":
        return ComponentId.DOCUMENTATION

    prefix = "src/cisco_assessment/"
    if not path.startswith(prefix):
        return ComponentId.UNKNOWN

    relative = path.removeprefix(prefix)
    if relative.startswith("collector/"):
        return ComponentId.COLLECTOR
    if relative.startswith("catalog/"):
        return ComponentId.COMMAND_CATALOG
    if relative.startswith("raw/") or relative == "models/raw.py":
        return ComponentId.RAW_MODELS
    if relative.startswith("models/"):
        return ComponentId.NORMALIZED_MODELS
    if relative.startswith("parsers/"):
        return ComponentId.PARSER
    if relative.startswith("reporting/"):
        return ComponentId.REPORTING
    if relative == "runner/plan.py":
        return ComponentId.ASSESSMENT_PLAN
    if relative.startswith("runner/") or relative == "cli.py":
        return ComponentId.RUNNER_CLI
    if relative.startswith("assessment/"):
        filename = pathlib.PurePosixPath(relative).name
        if filename == "rules.py" or filename.endswith("_rules.py"):
            return ComponentId.RULES
        return ComponentId.ENGINE

    return ComponentId.UNKNOWN


def classify_changed_files(
    changed_files: collections.abc.Iterable[GitHubChangedFile],
) -> tuple[ChangedFileClassification, ...]:
    """Classify changed files in canonical repository-path order."""
    return tuple(
        ChangedFileClassification(path=item.path, component=classify_changed_path(item.path))
        for item in sorted(changed_files, key=lambda item: item.path)
    )


def detected_components(context: PullRequestContext) -> tuple[ComponentId, ...]:
    """Return unique changed components in stable ComponentId declaration order."""
    observed = {item.component for item in classify_changed_files(context.changed_files)}
    return tuple(component for component in _COMPONENT_ORDER if component in observed)


def evaluate_scope_checks(
    request: ReviewRequest,
    context: PullRequestContext,
) -> tuple[ReviewCheck, ReviewCheck]:
    """Evaluate the first blocking scope checks against the actual changed files."""
    classifications = classify_changed_files(context.changed_files)
    return (
        _evaluate_authorized_scope(request, classifications),
        _evaluate_prohibited_scope(request, classifications),
    )


def _evaluate_authorized_scope(
    request: ReviewRequest,
    classifications: tuple[ChangedFileClassification, ...],
) -> ReviewCheck:
    allowed = set(request.expected_components)
    unexpected = tuple(item for item in classifications if item.component not in allowed)

    evidence = tuple(
        _scope_evidence(
            check_id=ReviewCheckId.SCOPE_001,
            ordinal=index,
            item=item,
            expectation="component must be within expected_components",
        )
        for index, item in enumerate(unexpected, start=1)
    )
    findings = tuple(
        ReviewFinding(
            finding_id=f"{ReviewCheckId.SCOPE_001.value}:{index:03d}",
            check_id=ReviewCheckId.SCOPE_001,
            severity=ReviewFindingSeverity.BLOCKING,
            title="Changed file is outside the authorized component scope",
            observation=(
                f"{item.path} is classified as {item.component.value}, which is not in the "
                "approved expected_components set."
            ),
            evidence=(evidence[index - 1],),
            recommendation="Remove the unrelated change or obtain explicit scope approval.",
        )
        for index, item in enumerate(unexpected, start=1)
    )

    if unexpected:
        return ReviewCheck(
            check_id=ReviewCheckId.SCOPE_001,
            name="Changed components match authorized scope",
            category="SCOPE",
            status=ReviewCheckStatus.FAIL,
            applicable=True,
            summary=f"{len(unexpected)} changed file(s) are outside the authorized scope.",
            evidence=evidence,
            findings=findings,
            blocking=True,
        )

    return ReviewCheck(
        check_id=ReviewCheckId.SCOPE_001,
        name="Changed components match authorized scope",
        category="SCOPE",
        status=ReviewCheckStatus.PASS,
        applicable=True,
        summary="All changed files are within the authorized component scope.",
        evidence=(),
        findings=(),
        blocking=True,
    )


def _evaluate_prohibited_scope(
    request: ReviewRequest,
    classifications: tuple[ChangedFileClassification, ...],
) -> ReviewCheck:
    if not request.prohibited_components:
        return ReviewCheck(
            check_id=ReviewCheckId.SCOPE_002,
            name="Explicitly prohibited components remain untouched",
            category="SCOPE",
            status=ReviewCheckStatus.NOT_APPLICABLE,
            applicable=False,
            summary="No explicitly prohibited components were supplied in the review request.",
            evidence=(),
            findings=(),
            blocking=True,
        )

    prohibited = set(request.prohibited_components)
    violations = tuple(item for item in classifications if item.component in prohibited)
    evidence = tuple(
        _scope_evidence(
            check_id=ReviewCheckId.SCOPE_002,
            ordinal=index,
            item=item,
            expectation="component must remain untouched",
        )
        for index, item in enumerate(violations, start=1)
    )
    findings = tuple(
        ReviewFinding(
            finding_id=f"{ReviewCheckId.SCOPE_002.value}:{index:03d}",
            check_id=ReviewCheckId.SCOPE_002,
            severity=ReviewFindingSeverity.BLOCKING,
            title="Explicitly prohibited component was modified",
            observation=(
                f"{item.path} is classified as {item.component.value}, which was explicitly "
                "prohibited by the review request."
            ),
            evidence=(evidence[index - 1],),
            recommendation="Remove the prohibited change or obtain explicit scope approval.",
        )
        for index, item in enumerate(violations, start=1)
    )

    if violations:
        return ReviewCheck(
            check_id=ReviewCheckId.SCOPE_002,
            name="Explicitly prohibited components remain untouched",
            category="SCOPE",
            status=ReviewCheckStatus.FAIL,
            applicable=True,
            summary=f"{len(violations)} changed file(s) touch explicitly prohibited components.",
            evidence=evidence,
            findings=findings,
            blocking=True,
        )

    return ReviewCheck(
        check_id=ReviewCheckId.SCOPE_002,
        name="Explicitly prohibited components remain untouched",
        category="SCOPE",
        status=ReviewCheckStatus.PASS,
        applicable=True,
        summary="No changed file touches an explicitly prohibited component.",
        evidence=(),
        findings=(),
        blocking=True,
    )


def _scope_evidence(
    *,
    check_id: ReviewCheckId,
    ordinal: int,
    item: ChangedFileClassification,
    expectation: str,
) -> ReviewEvidence:
    return ReviewEvidence(
        evidence_id=f"{check_id.value}:ev:{ordinal:03d}",
        kind=ReviewEvidenceKind.FILE,
        description=f"Changed repository file classified as {item.component.value}.",
        repository_path=item.path,
        check_id=check_id,
        observed_value=item.component.value,
        expected_value=expectation,
    )
