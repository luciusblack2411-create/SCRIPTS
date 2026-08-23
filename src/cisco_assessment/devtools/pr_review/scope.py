"""Deterministic changed-file classification and approved-scope checks."""

from __future__ import annotations

import collections.abc
import pathlib

from . import check_ids as _check_ids
from . import enums as _enums
from . import github as _github
from . import models as _models


_COMPONENT_ORDER: tuple[_enums.ComponentId, ...] = tuple(_enums.ComponentId)


class ChangedFileClassification:
    """Deterministic classification of one GitHub changed path."""

    __slots__ = ("component", "path")

    def __init__(self, path: str, component: _enums.ComponentId) -> None:
        self.path = path
        self.component = component

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ChangedFileClassification):
            return NotImplemented
        return self.path == other.path and self.component is other.component

    def __repr__(self) -> str:
        return f"ChangedFileClassification(path={self.path!r}, component={self.component!r})"


def classify_changed_path(path: str) -> _enums.ComponentId:
    """Classify a repository path without inspecting or inferring file contents."""
    pure_path = pathlib.PurePosixPath(path)
    parts = pure_path.parts

    if not parts:
        return _enums.ComponentId.UNKNOWN

    if parts[0] == "tests":
        return _enums.ComponentId.TESTING_FIXTURES
    if parts[0] == ".github" or path == "pyproject.toml":
        return _enums.ComponentId.CI_TOOLING
    if path.startswith("src/cisco_assessment/devtools/"):
        return _enums.ComponentId.CI_TOOLING
    if parts[0] == "docs" or path == "README.md":
        return _enums.ComponentId.DOCUMENTATION

    prefix = "src/cisco_assessment/"
    if not path.startswith(prefix):
        return _enums.ComponentId.UNKNOWN

    relative = path.removeprefix(prefix)
    if relative.startswith("collector/"):
        return _enums.ComponentId.COLLECTOR
    if relative.startswith("catalog/"):
        return _enums.ComponentId.COMMAND_CATALOG
    if relative.startswith("raw/") or relative == "models/raw.py":
        return _enums.ComponentId.RAW_MODELS
    if relative.startswith("models/"):
        return _enums.ComponentId.NORMALIZED_MODELS
    if relative.startswith("parsers/"):
        return _enums.ComponentId.PARSER
    if relative.startswith("reporting/"):
        return _enums.ComponentId.REPORTING
    if relative == "runner/plan.py":
        return _enums.ComponentId.ASSESSMENT_PLAN
    if relative.startswith("runner/") or relative == "cli.py":
        return _enums.ComponentId.RUNNER_CLI
    if relative.startswith("assessment/"):
        filename = pathlib.PurePosixPath(relative).name
        if filename == "rules.py" or filename.endswith("_rules.py"):
            return _enums.ComponentId.RULES
        return _enums.ComponentId.ENGINE

    return _enums.ComponentId.UNKNOWN


def classify_changed_files(
    changed_files: collections.abc.Iterable[_github.GitHubChangedFile],
) -> tuple[ChangedFileClassification, ...]:
    """Classify changed files in canonical repository-path order."""
    return tuple(
        ChangedFileClassification(path=item.path, component=classify_changed_path(item.path))
        for item in sorted(changed_files, key=lambda item: item.path)
    )


def detected_components(context: _github.PullRequestContext) -> tuple[_enums.ComponentId, ...]:
    """Return unique changed components in stable ComponentId declaration order."""
    observed = {item.component for item in classify_changed_files(context.changed_files)}
    return tuple(component for component in _COMPONENT_ORDER if component in observed)


def evaluate_scope_checks(
    request: _models.ReviewRequest,
    context: _github.PullRequestContext,
) -> tuple[_models.ReviewCheck, _models.ReviewCheck]:
    """Evaluate the first blocking scope checks against the actual changed files."""
    classifications = classify_changed_files(context.changed_files)
    return (
        _evaluate_authorized_scope(request, classifications),
        _evaluate_prohibited_scope(request, classifications),
    )


def _evaluate_authorized_scope(
    request: _models.ReviewRequest,
    classifications: tuple[ChangedFileClassification, ...],
) -> _models.ReviewCheck:
    allowed = set(request.expected_components)
    unexpected = tuple(item for item in classifications if item.component not in allowed)

    evidence = tuple(
        _scope_evidence(
            check_id=_check_ids.ReviewCheckId.SCOPE_001,
            ordinal=index,
            item=item,
            expectation="component must be within expected_components",
        )
        for index, item in enumerate(unexpected, start=1)
    )
    findings = tuple(
        _models.ReviewFinding(
            finding_id=f"{_check_ids.ReviewCheckId.SCOPE_001.value}:{index:03d}",
            check_id=_check_ids.ReviewCheckId.SCOPE_001,
            severity=_enums.ReviewFindingSeverity.BLOCKING,
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
        return _models.ReviewCheck(
            check_id=_check_ids.ReviewCheckId.SCOPE_001,
            name="Changed components match authorized scope",
            category="SCOPE",
            status=_enums.ReviewCheckStatus.FAIL,
            applicable=True,
            summary=f"{len(unexpected)} changed file(s) are outside the authorized scope.",
            evidence=evidence,
            findings=findings,
            blocking=True,
        )

    return _models.ReviewCheck(
        check_id=_check_ids.ReviewCheckId.SCOPE_001,
        name="Changed components match authorized scope",
        category="SCOPE",
        status=_enums.ReviewCheckStatus.PASS,
        applicable=True,
        summary="All changed files are within the authorized component scope.",
        evidence=(),
        findings=(),
        blocking=True,
    )


def _evaluate_prohibited_scope(
    request: _models.ReviewRequest,
    classifications: tuple[ChangedFileClassification, ...],
) -> _models.ReviewCheck:
    if not request.prohibited_components:
        return _models.ReviewCheck(
            check_id=_check_ids.ReviewCheckId.SCOPE_002,
            name="Explicitly prohibited components remain untouched",
            category="SCOPE",
            status=_enums.ReviewCheckStatus.NOT_APPLICABLE,
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
            check_id=_check_ids.ReviewCheckId.SCOPE_002,
            ordinal=index,
            item=item,
            expectation="component must remain untouched",
        )
        for index, item in enumerate(violations, start=1)
    )
    findings = tuple(
        _models.ReviewFinding(
            finding_id=f"{_check_ids.ReviewCheckId.SCOPE_002.value}:{index:03d}",
            check_id=_check_ids.ReviewCheckId.SCOPE_002,
            severity=_enums.ReviewFindingSeverity.BLOCKING,
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
        return _models.ReviewCheck(
            check_id=_check_ids.ReviewCheckId.SCOPE_002,
            name="Explicitly prohibited components remain untouched",
            category="SCOPE",
            status=_enums.ReviewCheckStatus.FAIL,
            applicable=True,
            summary=f"{len(violations)} changed file(s) touch explicitly prohibited components.",
            evidence=evidence,
            findings=findings,
            blocking=True,
        )

    return _models.ReviewCheck(
        check_id=_check_ids.ReviewCheckId.SCOPE_002,
        name="Explicitly prohibited components remain untouched",
        category="SCOPE",
        status=_enums.ReviewCheckStatus.PASS,
        applicable=True,
        summary="No changed file touches an explicitly prohibited component.",
        evidence=(),
        findings=(),
        blocking=True,
    )


def _scope_evidence(
    *,
    check_id: _check_ids.ReviewCheckId,
    ordinal: int,
    item: ChangedFileClassification,
    expectation: str,
) -> _models.ReviewEvidence:
    return _models.ReviewEvidence(
        evidence_id=f"{check_id.value}:ev:{ordinal:03d}",
        kind=_enums.ReviewEvidenceKind.FILE,
        description=f"Changed repository file classified as {item.component.value}.",
        repository_path=item.path,
        check_id=check_id,
        observed_value=item.component.value,
        expected_value=expectation,
    )
