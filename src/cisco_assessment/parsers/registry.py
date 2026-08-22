"""Explicit parser registry."""

from __future__ import annotations

from typing import Any

from cisco_assessment.catalog.enums import ParserId
from cisco_assessment.models.enums import PlatformFamily

from .base import BaseParser
from .errors import DuplicateParserError, ParserNotFoundError, UnsupportedPlatformError


class ParserRegistry:
    """Resolve parser implementations by stable catalog ``ParserId``."""

    def __init__(self) -> None:
        self._parsers: dict[ParserId, BaseParser[Any]] = {}

    def register(self, parser: BaseParser[Any]) -> None:
        parser_id = parser.descriptor.parser_id
        if parser_id in self._parsers:
            raise DuplicateParserError(
                f"Parser already registered: {parser_id.value}",
                parser_id=parser_id,
            )
        self._parsers[parser_id] = parser

    def resolve(
        self,
        parser_id: ParserId,
        platform: PlatformFamily,
    ) -> BaseParser[Any]:
        try:
            parser = self._parsers[parser_id]
        except KeyError as exc:
            raise ParserNotFoundError(
                f"No parser registered for {parser_id.value}",
                parser_id=parser_id,
            ) from exc

        if platform not in parser.descriptor.supported_platforms:
            raise UnsupportedPlatformError(parser_id, platform)

        return parser
