"""Explicit assessment rule catalog kept separate from engine execution."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Generic, TypeVar

from pydantic import BaseModel

from .rules import AssessmentRule

NormalizedT = TypeVar("NormalizedT", bound=BaseModel)


class DuplicateRuleError(ValueError):
    """Raised when a catalog contains more than one rule with the same stable ID."""


class RuleCatalog(Generic[NormalizedT]):
    """Immutable, deterministic collection of rules for one normalized model type."""

    def __init__(self, rules: Iterable[AssessmentRule[NormalizedT]] = ()) -> None:
        ordered = tuple(sorted(rules, key=lambda rule: rule.metadata.rule_id))
        ids = [rule.metadata.rule_id for rule in ordered]
        if len(ids) != len(set(ids)):
            raise DuplicateRuleError("assessment rule IDs must be unique")
        self._rules = ordered

    @property
    def rules(self) -> tuple[AssessmentRule[NormalizedT], ...]:
        return self._rules
