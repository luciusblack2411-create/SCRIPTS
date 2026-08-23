"""Deterministic architecture-boundary and Cisco read-only safety checks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cisco_assessment.devtools.pr_review.check_ids import ReviewCheckId
from cisco_assessment.devtools.pr_review.enums import (
    ComponentId,
    ReviewCheckStatus,
    ReviewEvidenceKind,
    ReviewFindingSeverity,
)
from cisco_assessment.devtools.pr_review.github import PullRequestContext
from cisco_assessment.devtools.pr_review.models import ReviewCheck, ReviewEvidence, ReviewFinding
from cisco_assessment.devtools.pr_review.scope import classify_changed_path, detected_components


@dataclass(frozen=True, slots=True)
class DiffAddedLine:
    """One added line extracted from a unified pull-request diff."""

    path: str
    line_number: int
    text: str
    component: ComponentId


@dataclass(frozen=True, slots=True)
class _ArchitectureBoundary:
    check_id: ReviewCheckId
    component: ComponentId
    name: str
    invariant: str
    forbidden_modules: tuple[str, ...]


_ARCHITECTURE_BOUNDARIES: tuple[_ArchitectureBoundary, ...] = (
    _ArchitectureBoundary(
        check_id=ReviewCheckId.ARCH_001,
        component=ComponentId.PARSER,
        name="Parsers remain extraction-only",
        invariant="Parsers must not depend on Collector, Assessment, Reporting, or Runner layers.",
        forbidden_modules=(
            "cisco_assessment.collector",
            "cisco_assessment.assessment",
            "cisco_assessment.reporting",
            "cisco_assessment.runner",
        ),
    ),
    _ArchitectureBoundary(
        check_id=ReviewCheckId.ARCH_002,
        component=ComponentId.ENGINE,
        name="Assessment Engine remains isolated from collection and parsing",
        invariant="Assessment Engine must not depend on Collector, Parsers, or Reporting.",
        forbidden_modules=(
            "cisco_assessment.collector",
            "cisco_assessment.parsers",
            "cisco_assessment.reporting",
        ),
    ),
    _ArchitectureBoundary(
        check_id=ReviewCheckId.ARCH_003,
        component=ComponentId.RULES,
        name="Rules depend only on normalized assessment inputs",
        invariant="Rules must not depend on Collector, Parsers, Reporting, Genie, pyATS, or Unicon.",
        forbidden_modules=(
            "cisco_assessment.collector",
            "cisco_assessment.parsers",
            "cisco_assessment.reporting",
            "genie",
            "pyats",
            "unicon",
        ),
    ),
    _ArchitectureBoundary(
        check_id=ReviewCheckId.ARCH_004,
        component=ComponentId.REPORTING,
        name="Reporting remains presentation-only",
        invariant="Reporting must not depend on Collector, Parsers, Genie, pyATS, or Unicon.",
        forbidden_modules=(
            "cisco_assessment.collector",
            "cisco_assessment.parsers",
            "genie",
            "pyats",
            "unicon",
        ),
    ),
    _ArchitectureBoundary(
        check_id=ReviewCheckId.ARCH_005,
        component=ComponentId.COLLECTOR,
        name="Collector remains transport-only",
        invariant="Collector must not depend on Parsers, Assessment, Reporting, Genie, pyATS, or Unicon.",
        forbidden_modules=(
            "cisco_assessment.parsers",
            "cisco_assessment.assessment",
            "cisco_assessment.reporting",
            "genie",
            "pyats",
            "unicon",
        ),
    ),
)

_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(?P<from>[A-Za-z_][\w.]*)\s+import\b|"
    r"import\s+(?P<import>[A-Za-z_][\w.]*))"
)
_HUNK_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(?P<new>\d+)(?:,\d+)?\s+@@")
_QUOTED_LITERAL_RE = re.compile(r"(?P<quote>['\"])(?P<value>[^'\"\n]+)(?P=quote)")

_READ_ONLY_SURFACES = frozenset(
    {
        ComponentId.COMMAND_CATALOG,
        ComponentId.COLLECTOR,
        ComponentId.ASSESSMENT_PLAN,
        ComponentId.RUNNER_CLI,
    }
)
_FORBIDDEN_CLI_PREFIXES: tuple[str, ...] = (
    "configure",
    "clear ",
    "reload",
    "reset ",
    "delete ",
    "erase ",
    "install ",
    "write ",
    "copy ",
    "terminal length ",
)
_SSH_MODULES: tuple[str, ...] = ("paramiko", "netmiko", "scrapli", "asyncssh", "unicon")


def extract_added_lines(diff_text: str) -> tuple[DiffAddedLine, ...]:
    """Extract added lines and their head-side line numbers from a unified diff."""
    current_path: str | None = None
    new_line_number: int | None = None
    added: list[DiffAddedLine] = []

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ "):
            candidate = raw_line[4:]
            current_path = candidate.removeprefix("b/")
            if current_path == "/dev/null":
                current_path = None
            new_line_number = None
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match is not None:
            new_line_number = int(hunk_match.group("new"))
            continue

        if current_path is None or new_line_number is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            added.append(
                DiffAddedLine(
                    path=current_path,
                    line_number=new_line_number,
                    text=raw_line[1:],
                    component=classify_changed_path(current_path),
                )
            )
            new_line_number += 1
            continue

        if raw_line.startswith("-") and not raw_line.startswith("---"):
            continue

        if raw_line.startswith(" ") or raw_line == "":
            new_line_number += 1

    return tuple(added)


def evaluate_architecture_safety_checks(context: PullRequestContext) -> tuple[ReviewCheck, ...]:
    """Evaluate architecture boundaries and read-only safety against added PR lines."""
    added_lines = extract_added_lines(context.diff_text)
    components = set(detected_components(context))
    architecture = tuple(
        _evaluate_architecture_boundary(boundary, components, added_lines)
        for boundary in _ARCHITECTURE_BOUNDARIES
    )
    return (
        *architecture,
        _evaluate_read_only_cli(components, added_lines),
        _evaluate_ssh_boundary(added_lines),
    )


def _evaluate_architecture_boundary(
    boundary: _ArchitectureBoundary,
    components: set[ComponentId],
    added_lines: tuple[DiffAddedLine, ...],
) -> ReviewCheck:
    if boundary.component not in components:
        return _not_applicable(
            check_id=boundary.check_id,
            name=boundary.name,
            category="ARCHITECTURE",
            summary=f"{boundary.component.value} is not changed by this pull request.",
        )

    violations: list[tuple[DiffAddedLine, str]] = []
    for line in added_lines:
        if line.component is not boundary.component:
            continue
        module = _imported_module(line.text)
        if module is None:
            continue
        if any(_module_matches(module, prefix) for prefix in boundary.forbidden_modules):
            violations.append((line, module))

    if not violations:
        return ReviewCheck(
            check_id=boundary.check_id,
            name=boundary.name,
            category="ARCHITECTURE",
            status=ReviewCheckStatus.PASS,
            applicable=True,
            summary="No newly added import crosses the protected layer boundary.",
            evidence=(),
            findings=(),
            blocking=True,
        )

    evidence = tuple(
        _line_evidence(
            check_id=boundary.check_id,
            ordinal=index,
            line=line,
            observed_value=module,
            expected_value=boundary.invariant,
        )
        for index, (line, module) in enumerate(violations, start=1)
    )
    findings = tuple(
        ReviewFinding(
            finding_id=f"{boundary.check_id.value}:{index:03d}",
            check_id=boundary.check_id,
            severity=ReviewFindingSeverity.BLOCKING,
            title="Protected architecture boundary was crossed",
            observation=(
                f"{line.path}:{line.line_number} adds an import of {module}, which violates "
                f"the {boundary.component.value} dependency boundary."
            ),
            violated_invariant=boundary.invariant,
            evidence=(evidence[index - 1],),
            recommendation=(
                "Remove the cross-layer dependency and keep the responsibility in its owning layer."
            ),
        )
        for index, (line, module) in enumerate(violations, start=1)
    )
    return ReviewCheck(
        check_id=boundary.check_id,
        name=boundary.name,
        category="ARCHITECTURE",
        status=ReviewCheckStatus.FAIL,
        applicable=True,
        summary=f"{len(violations)} newly added import(s) cross the protected layer boundary.",
        evidence=evidence,
        findings=findings,
        blocking=True,
    )


def _evaluate_read_only_cli(
    components: set[ComponentId],
    added_lines: tuple[DiffAddedLine, ...],
) -> ReviewCheck:
    check_id = ReviewCheckId.SAFE_001
    if not components.intersection(_READ_ONLY_SURFACES):
        return _not_applicable(
            check_id=check_id,
            name="Productive Cisco command surfaces remain read-only",
            category="SAFETY",
            summary=(
                "No command-definition or command-execution surface is changed by this pull request."
            ),
        )

    violations: list[tuple[DiffAddedLine, str]] = []
    for line in added_lines:
        if line.component not in _READ_ONLY_SURFACES:
            continue
        for literal in _quoted_literals(line.text):
            normalized = " ".join(literal.strip().lower().split())
            if _starts_with_forbidden_cli(normalized):
                violations.append((line, literal))

    if not violations:
        return ReviewCheck(
            check_id=check_id,
            name="Productive Cisco command surfaces remain read-only",
            category="SAFETY",
            status=ReviewCheckStatus.PASS,
            applicable=True,
            summary="No newly added state-changing Cisco CLI literal was detected.",
            evidence=(),
            findings=(),
            blocking=True,
        )

    invariant = "Productive Cisco execution must remain read-only; state-changing CLI is prohibited."
    evidence = tuple(
        _line_evidence(
            check_id=check_id,
            ordinal=index,
            line=line,
            observed_value=literal,
            expected_value=invariant,
        )
        for index, (line, literal) in enumerate(violations, start=1)
    )
    findings = tuple(
        ReviewFinding(
            finding_id=f"{check_id.value}:{index:03d}",
            check_id=check_id,
            severity=ReviewFindingSeverity.BLOCKING,
            title="State-changing Cisco CLI literal was added",
            observation=(
                f"{line.path}:{line.line_number} adds a Cisco CLI literal that begins with a "
                "prohibited state-changing command."
            ),
            violated_invariant=invariant,
            evidence=(evidence[index - 1],),
            recommendation="Remove the state-changing command; productive assessments are read-only.",
        )
        for index, (line, _literal) in enumerate(violations, start=1)
    )
    return ReviewCheck(
        check_id=check_id,
        name="Productive Cisco command surfaces remain read-only",
        category="SAFETY",
        status=ReviewCheckStatus.FAIL,
        applicable=True,
        summary=f"{len(violations)} newly added state-changing Cisco CLI literal(s) were detected.",
        evidence=evidence,
        findings=findings,
        blocking=True,
    )


def _evaluate_ssh_boundary(added_lines: tuple[DiffAddedLine, ...]) -> ReviewCheck:
    check_id = ReviewCheckId.SAFE_002
    productive_non_collector = tuple(
        line
        for line in added_lines
        if line.path.startswith("src/cisco_assessment/")
        and not line.path.startswith("src/cisco_assessment/devtools/")
        and line.component is not ComponentId.COLLECTOR
    )
    if not productive_non_collector:
        return _not_applicable(
            check_id=check_id,
            name="SSH libraries remain behind the Collector boundary",
            category="SAFETY",
            summary="No productive non-Collector source line was added by this pull request.",
        )

    violations: list[tuple[DiffAddedLine, str]] = []
    for line in productive_non_collector:
        module = _imported_module(line.text)
        if module is None:
            continue
        if any(_module_matches(module, prefix) for prefix in _SSH_MODULES):
            violations.append((line, module))

    if not violations:
        return ReviewCheck(
            check_id=check_id,
            name="SSH libraries remain behind the Collector boundary",
            category="SAFETY",
            status=ReviewCheckStatus.PASS,
            applicable=True,
            summary="No newly added productive import bypasses the Collector SSH boundary.",
            evidence=(),
            findings=(),
            blocking=True,
        )

    invariant = "External SSH libraries must remain behind project-owned Collector abstractions."
    evidence = tuple(
        _line_evidence(
            check_id=check_id,
            ordinal=index,
            line=line,
            observed_value=module,
            expected_value=invariant,
        )
        for index, (line, module) in enumerate(violations, start=1)
    )
    findings = tuple(
        ReviewFinding(
            finding_id=f"{check_id.value}:{index:03d}",
            check_id=check_id,
            severity=ReviewFindingSeverity.BLOCKING,
            title="SSH dependency bypasses the Collector boundary",
            observation=(
                f"{line.path}:{line.line_number} adds a direct import of {module} outside Collector."
            ),
            violated_invariant=invariant,
            evidence=(evidence[index - 1],),
            recommendation="Move transport access behind the project-owned Collector abstraction.",
        )
        for index, (line, module) in enumerate(violations, start=1)
    )
    return ReviewCheck(
        check_id=check_id,
        name="SSH libraries remain behind the Collector boundary",
        category="SAFETY",
        status=ReviewCheckStatus.FAIL,
        applicable=True,
        summary=f"{len(violations)} newly added SSH import(s) bypass the Collector boundary.",
        evidence=evidence,
        findings=findings,
        blocking=True,
    )


def _imported_module(text: str) -> str | None:
    match = _IMPORT_RE.match(text)
    if match is None:
        return None
    return match.group("from") or match.group("import")


def _module_matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _quoted_literals(text: str) -> tuple[str, ...]:
    return tuple(match.group("value") for match in _QUOTED_LITERAL_RE.finditer(text))


def _starts_with_forbidden_cli(normalized: str) -> bool:
    return any(
        normalized == prefix.rstrip() or normalized.startswith(prefix)
        for prefix in _FORBIDDEN_CLI_PREFIXES
    )


def _line_evidence(
    *,
    check_id: ReviewCheckId,
    ordinal: int,
    line: DiffAddedLine,
    observed_value: str,
    expected_value: str,
) -> ReviewEvidence:
    return ReviewEvidence(
        evidence_id=f"{check_id.value}:ev:{ordinal:03d}",
        kind=ReviewEvidenceKind.SOURCE_LINE,
        description="Added pull-request source line violates a protected review invariant.",
        repository_path=line.path,
        line_start=line.line_number,
        line_end=line.line_number,
        check_id=check_id,
        observed_value=observed_value,
        expected_value=expected_value,
    )


def _not_applicable(
    *,
    check_id: ReviewCheckId,
    name: str,
    category: str,
    summary: str,
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
        blocking=True,
    )
