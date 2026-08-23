"""Parser framework public API."""

from .base import BaseParser
from .errors import (
    CommandMismatchError,
    DuplicateParserError,
    EmptyRawOutputError,
    GenieDependencyError,
    GenieExtractionError,
    ParserError,
    ParserErrorCode,
    ParserNotFoundError,
    TraceabilityMismatchError,
    UnrecognizedFormatError,
    UnsupportedPlatformError,
)
from .ios import IOSShowInterfacesStatusParser, IOSShowInventoryParser, IOSShowVersionParser
from .models import (
    FieldEvidence,
    ParsedPayload,
    ParserDescriptor,
    ParseResult,
    ParserWarning,
    ParseStatus,
    ParseTrace,
)
from .registry import ParserRegistry


def build_parser_registry() -> ParserRegistry:
    """Build the explicit productive parser registry."""
    registry = ParserRegistry()
    registry.register(IOSShowVersionParser())
    registry.register(IOSShowInventoryParser())
    registry.register(IOSShowInterfacesStatusParser())
    return registry


__all__ = [
    "BaseParser",
    "CommandMismatchError",
    "DuplicateParserError",
    "EmptyRawOutputError",
    "FieldEvidence",
    "GenieDependencyError",
    "GenieExtractionError",
    "IOSShowInterfacesStatusParser",
    "IOSShowInventoryParser",
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
