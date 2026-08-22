"""JSON renderer for the canonical AssessmentReport."""

from __future__ import annotations

import json

from ..models import AssessmentReport, RenderedReport


class JsonReportRenderer:
    """Serialize AssessmentReport to deterministic UTF-8 JSON bytes."""

    media_type = "application/json"
    extension = ".json"

    def render(self, report: AssessmentReport) -> RenderedReport:
        payload = json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        return RenderedReport(
            content=payload + b"\n",
            media_type=self.media_type,
            extension=self.extension,
        )
