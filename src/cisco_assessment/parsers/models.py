"""Shared parser contracts, results, evidence, and traceability."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models.enums import PlatformFamily


NormalizedT = TypeVar("NormalizedT", bound=BaseModel)


class ParseStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class ParserDescriptor:
    parser_id: ParserId
    parser_version: str
    command_id: CommandId
    normalized_model: NormalizedModelId
    supported_platforms: frozenset[PlatformFamily]


@dataclass(frozen=True, slots=True)
class ParserWarning:
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    field: str
    extractor: str
    line_start: int
    line_end: int


@dataclass(frozen=True, slots=True)
class ParseTrace:
    assessment_run_id: UUID
    command_execution_id: UUID
    raw_output_id: UUID
    raw_sha256: str
    command_id: CommandId
    parser_id: ParserId
    parser_version: str
    normalized_model: NormalizedModelId
    platform: PlatformFamily


@dataclass(frozen=True, slots=True)
class ParsedPayload(Generic[NormalizedT]):
    data: NormalizedT
    warnings: tuple[ParserWarning, ...] = ()
    evidence: tuple[FieldEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class ParseResult(Generic[NormalizedT]):
    status: ParseStatus
    data: NormalizedT
    trace: ParseTrace
    warnings: tuple[ParserWarning, ...] = ()
    evidence: tuple[FieldEvidence, ...] = ()
