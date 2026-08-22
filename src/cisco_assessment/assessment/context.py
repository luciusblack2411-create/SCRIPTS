"""Evaluation context passed to deterministic assessment rules."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from cisco_assessment.models.enums import PlatformFamily

from .evidence import NormalizedFieldSource, SourceTrace


class AssessmentContext(BaseModel):
    """Immutable context and provenance available to assessment evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assessment_run_id: UUID
    device_id: UUID
    platform: PlatformFamily
    source_evidence: tuple[NormalizedFieldSource, ...] = ()

    @model_validator(mode="after")
    def validate_source_trace(self) -> Self:
        for item in self.source_evidence:
            if item.source.assessment_run_id != self.assessment_run_id:
                raise ValueError("source evidence assessment_run_id does not match context")
            if item.source.platform != self.platform:
                raise ValueError("source evidence platform does not match context")
        return self

    def sources_for(self, normalized_model: str, field_path: str) -> tuple[SourceTrace, ...]:
        """Resolve zero or more RAW source references for a normalized field."""
        return tuple(
            item.source
            for item in self.source_evidence
            if item.normalized_model == normalized_model and item.field_path == field_path
        )
