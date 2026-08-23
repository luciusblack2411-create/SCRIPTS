"""Typed contracts for PR Review Agent v0.1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .check_ids import ReviewCheckId
from .enums import (
    ComponentId,
    ReviewCheckStatus,
    ReviewDecision,
    ReviewEvidenceKind,
    ReviewFindingSeverity,
)

AGENT_ID: Literal["PR_REVIEW_AGENT_V1"] = "PR_REVIEW_AGENT_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class FrozenReviewModel(BaseModel):
    """Strict immutable base model for review-agent contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReviewRequest(FrozenReviewModel):
    """Inputs required to review one pull request against approved scope."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["PR_REVIEW_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    expected_base_branch: str = Field(default="main", min_length=1)
    objective: str = Field(min_length=1)
    expected_components: tuple[ComponentId, ...]
    prohibited_components: tuple[ComponentId, ...] = ()
    expected_contracts: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    related_issue_ids: tuple[str, ...] = ()
    related_milestone: str | None = None
    handoff_text: str | None = None
    require_ci_success: bool = True


class ReviewEvidence(FrozenReviewModel):
    """Verifiable evidence supporting a check or finding."""

    evidence_id: str = Field(min_length=1)
    kind: ReviewEvidenceKind
    description: str = Field(min_length=1)
    repository_path: str | None = None
    commit_sha: str | None = None
    line_start: int | None = Field(default=None, gt=0)
    line_end: int | None = Field(default=None, gt=0)
    check_id: ReviewCheckId | None = None
    command: str | None = None
    observed_value: str | None = None
    expected_value: str | None = None

    @model_validator(mode="after")
    def validate_line_range(self) -> ReviewEvidence:
        """Require complete, ordered source-line ranges when line evidence is used."""
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line_start and line_end must be provided together")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class ReviewFinding(FrozenReviewModel):
    """One evidence-backed observation raised by a review check."""

    finding_id: str = Field(min_length=1)
    check_id: ReviewCheckId
    severity: ReviewFindingSeverity
    title: str = Field(min_length=1)
    observation: str = Field(min_length=1)
    violated_invariant: str | None = None
    evidence: tuple[ReviewEvidence, ...]
    recommendation: str | None = None
    requires_human_decision: bool = False

    @model_validator(mode="after")
    def validate_finding_evidence(self) -> ReviewFinding:
        """Require evidence for blockers and preserve check/evidence consistency."""
        if self.severity is ReviewFindingSeverity.BLOCKING and not self.evidence:
            raise ValueError("blocking findings require at least one evidence item")
        if any(
            item.check_id is not None and item.check_id is not self.check_id
            for item in self.evidence
        ):
            raise ValueError("finding evidence check_id must match finding check_id")
        return self


class ReviewCheck(FrozenReviewModel):
    """Structured result of evaluating one stable review check."""

    check_id: ReviewCheckId
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    status: ReviewCheckStatus
    applicable: bool
    summary: str = Field(min_length=1)
    evidence: tuple[ReviewEvidence, ...]
    findings: tuple[ReviewFinding, ...]
    blocking: bool

    @model_validator(mode="after")
    def validate_check_consistency(self) -> ReviewCheck:
        """Keep applicability, evidence, and findings internally consistent."""
        if self.applicable and self.status is ReviewCheckStatus.NOT_APPLICABLE:
            raise ValueError("applicable checks cannot have NOT_APPLICABLE status")
        if not self.applicable and self.status is not ReviewCheckStatus.NOT_APPLICABLE:
            raise ValueError("non-applicable checks must have NOT_APPLICABLE status")
        if any(
            item.check_id is not None and item.check_id is not self.check_id
            for item in self.evidence
        ):
            raise ValueError("check evidence check_id must match check check_id")
        if any(finding.check_id is not self.check_id for finding in self.findings):
            raise ValueError("check findings must use the same check_id as the check")
        has_evidence = bool(self.evidence) or any(finding.evidence for finding in self.findings)
        if self.blocking and self.status is ReviewCheckStatus.FAIL and not has_evidence:
            raise ValueError("blocking failed checks require evidence")
        return self


class ReviewReport(FrozenReviewModel):
    """Canonical structured output of one PR review execution."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["PR_REVIEW_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    head_branch: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    mergeable: bool | None
    objective: str = Field(min_length=1)
    detected_components: tuple[ComponentId, ...]
    checks: tuple[ReviewCheck, ...]
    findings: tuple[ReviewFinding, ...]
    contracts_changed: tuple[str, ...]
    contracts_verified_stable: tuple[str, ...]
    residual_risks: tuple[str, ...]
    decision: ReviewDecision
    decision_reason: str = Field(min_length=1)
