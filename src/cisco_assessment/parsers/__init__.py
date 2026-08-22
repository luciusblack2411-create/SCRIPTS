"""Parser framework public API."""

from .base import BaseParser
from .errors import (
    CommandMismatchError,
    DuplicateParserError,
    EmptyRawOutputError,
    ParserError,
    ParserErrorCode,
    ParserNotFoundError,
    TraceabilityMismatchError,
    UnrecognizedFormatError,
    UnsupportedPlatformError,
)
from .ios import IOSShowVersionParser
from .models import (
    FieldEvidence,
    ParseResult,
    ParseStatus,
    ParseTrace,
    ParsedPayload,
    ParserDescriptor,
    ParserWarning,
)
from .registry import ParserRegistry


def build_parser_registry() -> ParserRegistry:
    """Build the explicit v0.1 parser registry."""
    registry = ParserRegistry()
    registry.register(IOSShowVersionParser())
    return registry


__all__ = [
    "BaseParser",
    "CommandMismatchError",
    "DuplicateParserError",
    "EmptyRawOutputError",
    "FieldEvidence",
    "IOSShowVersionParser",
    "ParseResult",
    "ParseStatus",
    "ParseTrace",
    "ParsedPayload",
    "ParserDescriptor",
    "ParserError",
    "ParserErrorCode",
    "ParserNotFoundError",
    "ParserRegistry",
    "ParserWarning",
    "TraceabilityMismatchError",
    "UnrecognizedFormatError",
    "UnsupportedPlatformError",
    "build_parser_registry",
]
