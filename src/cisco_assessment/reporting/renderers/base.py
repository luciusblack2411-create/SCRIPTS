"""Renderer contract for canonical assessment reports."""

from __future__ import annotations

from typing import Protocol

from ..models import AssessmentReport, RenderedReport


class ReportRenderer(Protocol):
    """Convert AssessmentReport into one presentation/output format."""

    media_type: str
    extension: str

    def render(self, report: AssessmentReport) -> RenderedReport:
        """Render a canonical report without consulting assessment-domain services."""
        ...
