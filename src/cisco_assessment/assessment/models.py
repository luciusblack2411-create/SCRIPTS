"""Typed contracts for assessment rules, outcomes, findings, and results."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cisco_assessment.models.enums import PlatformFamily

from .enums import AssessmentStatus, FindingSeverity
from .evidence import EvidenceRequest, FindingEvidence


class RuleMetadata(BaseModel):
    """Stable metadata declared by one assessment rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Z0-9][A-Z0-9_.-]*$")
    version: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=1024)
    category: str = Field(min_length=1, max_length=128)
    severity: FindingSeverity
    normalized_model: str = Field(min_length=1, max_length=128)
    supported_platforms: frozenset[PlatformFamily]


class RuleDecision(BaseModel):
    """Parser/RAW-agnostic decision returned by deterministic rule logic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AssessmentStatus
    message: str = Field(min_length=1, max_length=2048)
    evidence: tuple[EvidenceRequest, ...] = ()
    recommendation: str | None = Field(default=None, min_length=1, max_length=2048)


class RuleOutcome(BaseModel):
    """Complete execution record for one rule, including PASS and N/A results."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    rule_version: str
    title: str
    category: str
    normalized_model: str
    status: AssessmentStatus
    severity: FindingSeverity
    message: str
    evidence: tuple[FindingEvidence, ...] = ()
    recommendation: str | None = None
    reason_code: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class Finding(BaseModel):
    """Reportable result derived from FAIL/WARNING/INFO/ERROR outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: UUID
    rule_id: str
    rule_version: str
    title: str
    description: str
    category: str
    normalized_model: str
    status: AssessmentStatus
    severity: FindingSeverity
    evidence: tuple[FindingEvidence, ...] = ()
    recommendation: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class AssessmentResult(BaseModel):
    """Structured result produced by one engine evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assessment_run_id: UUID
    device_id: UUID
    platform: PlatformFamily
    normalized_model: str
    outcomes: tuple[RuleOutcome, ...]
    findings: tuple[Finding, ...]
