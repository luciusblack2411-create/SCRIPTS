"""Common parser interface and RAW/traceability boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.execution import CommandExecution
from cisco_assessment.models.raw import RawCommandOutput

from .errors import (
    CommandMismatchError,
    EmptyRawOutputError,
    ParserError,
    TraceabilityMismatchError,
    UnsupportedPlatformError,
)
from .models import (
    ParseResult,
    ParseStatus,
    ParseTrace,
    ParsedPayload,
    ParserDescriptor,
    ParserWarning,
)


NormalizedT = TypeVar("NormalizedT", bound=BaseModel)


class BaseParser(ABC, Generic[NormalizedT]):
    """Template-method parser contract.

    Subclasses only receive immutable RAW text content and platform. Persistence
    and execution metadata stay outside parsing logic, while this boundary
    validates and records source traceability.
    """

    @property
    @abstractmethod
    def descriptor(self) -> ParserDescriptor:
        raise NotImplementedError

    def parse(
        self,
        *,
        raw_output: RawCommandOutput,
        command_execution: CommandExecution,
        platform: PlatformFamily,
    ) -> ParseResult[NormalizedT]:
        descriptor = self.descriptor

        if raw_output.command_execution_id != command_execution.id:
            raise TraceabilityMismatchError(
                "RawCommandOutput.command_execution_id does not match CommandExecution.id",
                parser_id=descriptor.parser_id,
                command_execution_id=command_execution.id,
                raw_output_id=raw_output.id,
            )

        if command_execution.command_key != descriptor.command_id.value:
            raise CommandMismatchError(
                (
                    f"CommandExecution.command_key={command_execution.command_key!r} "
                    f"does not match parser command {descriptor.command_id.value!r}"
                ),
                parser_id=descriptor.parser_id,
                command_execution_id=command_execution.id,
                raw_output_id=raw_output.id,
            )

        if platform not in descriptor.supported_platforms:
            raise UnsupportedPlatformError(descriptor.parser_id, platform)

        if not raw_output.content.strip():
            raise EmptyRawOutputError(
                "RAW command output is empty",
                parser_id=descriptor.parser_id,
                command_execution_id=command_execution.id,
                raw_output_id=raw_output.id,
            )

        try:
            payload = self._parse_content(raw_output.content, platform)
        except ParserError as exc:
            exc.attach_trace(
                parser_id=descriptor.parser_id,
                command_execution_id=command_execution.id,
                raw_output_id=raw_output.id,
            )
            raise

        warnings = list(payload.warnings)
        if raw_output.is_truncated:
            warnings.append(
                ParserWarning(
                    code="raw_truncated",
                    message="RAW output is marked as truncated; normalized data may be incomplete.",
                )
            )

        trace = ParseTrace(
            assessment_run_id=command_execution.assessment_run_id,
            command_execution_id=command_execution.id,
            raw_output_id=raw_output.id,
            raw_sha256=raw_output.sha256,
            command_id=descriptor.command_id,
            parser_id=descriptor.parser_id,
            parser_version=descriptor.parser_version,
            normalized_model=descriptor.normalized_model,
            platform=platform,
        )

        return ParseResult(
            status=ParseStatus.PARTIAL if warnings else ParseStatus.SUCCESS,
            data=payload.data,
            trace=trace,
            warnings=tuple(warnings),
            evidence=payload.evidence,
        )

    @abstractmethod
    def _parse_content(
        self,
        content: str,
        platform: PlatformFamily,
    ) -> ParsedPayload[NormalizedT]:
        raise NotImplementedError
