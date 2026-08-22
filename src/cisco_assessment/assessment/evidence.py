"""Normalized-field evidence contracts used by the assessment layer."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from cisco_assessment.models.enums import PlatformFamily


class SourceTrace(BaseModel):
    """Parser-agnostic reference back to the RAW evidence that produced a field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assessment_run_id: UUID
    command_execution_id: UUID
    raw_output_id: UUID
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_id: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=64)
    platform: PlatformFamily
    extractor: str | None = Field(default=None, min_length=1, max_length=128)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> SourceTrace:
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line_start and line_end must either both be set or both be omitted")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class NormalizedFieldSource(BaseModel):
    """Source trace associated with one normalized model field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    normalized_model: str = Field(min_length=1, max_length=128)
    field_path: str = Field(min_length=1, max_length=256)
    source: SourceTrace


class EvidenceRequest(BaseModel):
    """Evidence requested by a rule without knowledge of parser or RAW internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str = Field(min_length=1, max_length=256)
    observed_value: JsonValue = None


class FindingEvidence(BaseModel):
    """Resolved evidence attached to a rule outcome or finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    normalized_model: str = Field(min_length=1, max_length=128)
    field_path: str = Field(min_length=1, max_length=256)
    observed_value: JsonValue = None
    sources: tuple[SourceTrace, ...] = ()
