"""Typed parser errors."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from cisco_assessment.catalog.enums import ParserId
from cisco_assessment.models.enums import PlatformFamily


class ParserErrorCode(StrEnum):
    EMPTY_RAW = "empty_raw"
    TRACEABILITY_MISMATCH = "traceability_mismatch"
    COMMAND_MISMATCH = "command_mismatch"
    PARSER_NOT_FOUND = "parser_not_found"
    DUPLICATE_PARSER = "duplicate_parser"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    UNRECOGNIZED_FORMAT = "unrecognized_format"


class ParserError(Exception):
    """Base typed parser failure with optional source identifiers."""

    code: ParserErrorCode

    def __init__(
        self,
        message: str,
        *,
        parser_id: ParserId | None = None,
        command_execution_id: UUID | None = None,
        raw_output_id: UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.parser_id = parser_id
        self.command_execution_id = command_execution_id
        self.raw_output_id = raw_output_id

    def attach_trace(
        self,
        *,
        parser_id: ParserId,
        command_execution_id: UUID,
        raw_output_id: UUID,
    ) -> None:
        """Attach source IDs when a parser-specific error did not already carry them."""
        if self.parser_id is None:
            self.parser_id = parser_id
        if self.command_execution_id is None:
            self.command_execution_id = command_execution_id
        if self.raw_output_id is None:
            self.raw_output_id = raw_output_id


class EmptyRawOutputError(ParserError):
    code = ParserErrorCode.EMPTY_RAW


class TraceabilityMismatchError(ParserError):
    code = ParserErrorCode.TRACEABILITY_MISMATCH


class CommandMismatchError(ParserError):
    code = ParserErrorCode.COMMAND_MISMATCH


class ParserNotFoundError(ParserError):
    code = ParserErrorCode.PARSER_NOT_FOUND


class DuplicateParserError(ParserError):
    code = ParserErrorCode.DUPLICATE_PARSER


class UnsupportedPlatformError(ParserError):
    code = ParserErrorCode.UNSUPPORTED_PLATFORM

    def __init__(
        self,
        parser_id: ParserId,
        platform: PlatformFamily,
    ) -> None:
        super().__init__(
            f"{parser_id.value} does not support platform {platform.value}",
            parser_id=parser_id,
        )
        self.platform = platform


class UnrecognizedFormatError(ParserError):
    code = ParserErrorCode.UNRECOGNIZED_FORMAT
