"""Assessment rule protocol independent from Collector and parser implementations."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from .context import AssessmentContext
from .models import RuleDecision, RuleMetadata

NormalizedT_contra = TypeVar("NormalizedT_contra", bound=BaseModel, contravariant=True)


class AssessmentRule(Protocol[NormalizedT_contra]):
    """Structural contract implemented by deterministic assessment rules."""

    @property
    def metadata(self) -> RuleMetadata:
        ...

    def evaluate(
        self,
        model: NormalizedT_contra,
        context: AssessmentContext,
    ) -> RuleDecision:
        ...
