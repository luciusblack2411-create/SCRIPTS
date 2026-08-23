from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.pr_review import (
    ComponentId,
    ReviewCheck,
    ReviewCheckId,
    ReviewCheckStatus,
    ReviewEvidence,
    ReviewEvidenceKind,
    ReviewFinding,
    ReviewFindingSeverity,
    ReviewRequest,
)


def _evidence() -> ReviewEvidence:
    return ReviewEvidence(
        evidence_id="ev-001",
        kind=ReviewEvidenceKind.SOURCE_LINE,
        description="Parser imports Reporting.",
        repository_path="src/cisco_assessment/parsers/example.py",
        line_start=10,
        line_end=10,
        check_id=ReviewCheckId.ARCH_003,
    )


def test_review_request_is_frozen_and_forbids_extra_fields() -> None:
    request = ReviewRequest(
        repository="owner/repo",
        pr_number=42,
        objective="Review parser-only change.",
        expected_components=(ComponentId.PARSER,),
    )

    with pytest.raises(ValidationError):
        setattr(request, "objective", "mutated")

    with pytest.raises(ValidationError):
        ReviewRequest.model_validate(
            {
                "repository": "owner/repo",
                "pr_number": 42,
                "objective": "Review parser-only change.",
                "expected_components": (ComponentId.PARSER,),
                "unexpected": True,
            }
        )


def test_review_evidence_requires_complete_ordered_line_range() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        ReviewEvidence(
            evidence_id="ev-001",
            kind=ReviewEvidenceKind.SOURCE_LINE,
            description="Incomplete line range.",
            line_start=10,
        )

    with pytest.raises(ValidationError, match="greater than or equal"):
        ReviewEvidence(
            evidence_id="ev-002",
            kind=ReviewEvidenceKind.SOURCE_LINE,
            description="Reversed line range.",
            line_start=11,
            line_end=10,
        )


def test_blocking_finding_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="blocking findings require"):
        ReviewFinding(
            finding_id="ARCH-003:001",
            check_id=ReviewCheckId.ARCH_003,
            severity=ReviewFindingSeverity.BLOCKING,
            title="Parser crosses architecture boundary",
            observation="Parser imports Reporting.",
            evidence=(),
        )


def test_non_applicable_check_requires_not_applicable_status() -> None:
    with pytest.raises(ValidationError, match="non-applicable checks"):
        ReviewCheck(
            check_id=ReviewCheckId.RULE_001,
            name="Stable RuleId",
            category="RULE",
            status=ReviewCheckStatus.PASS,
            applicable=False,
            summary="Rules are outside this PR scope.",
            evidence=(),
            findings=(),
            blocking=True,
        )


def test_blocking_finding_with_evidence_is_valid() -> None:
    finding = ReviewFinding(
        finding_id="ARCH-003:001",
        check_id=ReviewCheckId.ARCH_003,
        severity=ReviewFindingSeverity.BLOCKING,
        title="Parser crosses architecture boundary",
        observation="Parser imports Reporting.",
        evidence=(_evidence(),),
        recommendation="Remove the Reporting dependency from the parser.",
    )

    assert finding.evidence[0].repository_path == "src/cisco_assessment/parsers/example.py"
