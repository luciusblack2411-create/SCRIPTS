"""IOS/IOS-XE ``show interfaces status`` parser backed by offline Genie extraction."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from pydantic import ValidationError

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.interface import InterfaceObservation, InterfaceStatusRecord

from ..base import BaseParser
from ..errors import GenieDependencyError, GenieExtractionError, UnrecognizedFormatError
from ..models import FieldEvidence, ParsedPayload, ParserDescriptor, ParserWarning

_STATUS_TOKENS = (
    "connected",
    "notconnect",
    "suspended",
    "inactive",
    "disabled",
    "err-disabled",
    "monitoring",
)
_STATUS_TOKEN_RE = re.compile(
    r"(?:^|\s)(?:" + "|".join(re.escape(token) for token in _STATUS_TOKENS) + r")(?:\s|$)"
)
_EXTRACTOR = "genie_show_interfaces_status+framework_raw_line_index"

GenieInterfaceValues = dict[str, object]
GenieInterfaces = dict[str, GenieInterfaceValues]
InterfaceNameConverter = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class _RawInterfaceRow:
    """A candidate RAW row used only for source-line correlation."""

    canonical_interface: str
    line_number: int
    raw_interface: str


class IOSShowInterfacesStatusParser(BaseParser[InterfaceObservation]):
    """Extract with Genie and adapt into the framework-owned interface contract."""

    _descriptor = ParserDescriptor(
        parser_id=ParserId.IOS_SHOW_INTERFACES_STATUS_V1,
        parser_version="0.1.0",
        command_id=CommandId.INTERFACES_STATUS,
        normalized_model=NormalizedModelId.INTERFACE_OBSERVATION,
        supported_platforms=frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE}),
    )

    @property
    def descriptor(self) -> ParserDescriptor:
        return self._descriptor

    def _parse_content(
        self,
        content: str,
        platform: PlatformFamily,
    ) -> ParsedPayload[InterfaceObservation]:
        genie_interfaces, convert_intf_name = self._extract_with_genie(content, platform)
        raw_rows = self._index_raw_rows(content, convert_intf_name)
        rows_by_interface = self._group_raw_rows(raw_rows)
        warnings = self._build_consistency_warnings(
            raw_rows=raw_rows,
            rows_by_interface=rows_by_interface,
            genie_interfaces=genie_interfaces,
        )

        records: list[InterfaceStatusRecord] = []
        evidence: list[FieldEvidence] = []
        source_lines: list[int] = []

        for interface, values in self._ordered_genie_items(genie_interfaces, rows_by_interface):
            ordinal = len(records) + 1
            record = self._adapt_record(
                ordinal=ordinal,
                interface=interface,
                values=values,
            )
            records.append(record)

            source_rows = rows_by_interface.get(interface, ())
            if len(source_rows) != 1:
                continue
            source_row = source_rows[0]
            source_lines.append(source_row.line_number)
            evidence.extend(
                self._field_evidence(
                    index=ordinal - 1,
                    record=record,
                    line_number=source_row.line_number,
                )
            )

        if not records:
            raise UnrecognizedFormatError(
                "Genie returned no usable show interfaces status records",
                parser_id=self.descriptor.parser_id,
            )

        if source_lines:
            evidence.insert(
                0,
                FieldEvidence(
                    field="interfaces",
                    extractor=_EXTRACTOR,
                    line_start=min(source_lines),
                    line_end=max(source_lines),
                ),
            )

        try:
            observation = InterfaceObservation(platform=platform, interfaces=tuple(records))
        except ValidationError as exc:
            raise UnrecognizedFormatError(
                "Genie interface data could not satisfy InterfaceObservation v0.1",
                parser_id=self.descriptor.parser_id,
            ) from exc

        return ParsedPayload(
            data=observation,
            warnings=tuple(warnings),
            evidence=tuple(evidence),
        )

    @classmethod
    def _extract_with_genie(
        cls,
        content: str,
        platform: PlatformFamily,
    ) -> tuple[GenieInterfaces, InterfaceNameConverter]:
        parser_module_name = (
            "genie.libs.parser.ios.show_interface"
            if platform is PlatformFamily.IOS
            else "genie.libs.parser.iosxe.show_interface"
        )
        try:
            parser_module = import_module(parser_module_name)
            common_module = import_module("genie.libs.parser.utils.common")
            genie_parser_type: Any = getattr(parser_module, "ShowInterfacesStatus")
            common_type: Any = getattr(common_module, "Common")
            converter: Any = getattr(common_type, "convert_intf_name")
        except (ImportError, AttributeError) as exc:
            raise GenieDependencyError(
                "Required Genie show interfaces status parser components are unavailable",
                parser_id=cls._descriptor.parser_id,
            ) from exc

        try:
            genie_parser: Any = genie_parser_type(device=None)
            parsed: Any = genie_parser.cli(output=content)
        except Exception as exc:
            raise GenieExtractionError(
                "Genie failed while extracting pre-collected show interfaces status output",
                parser_id=cls._descriptor.parser_id,
            ) from exc

        if not isinstance(parsed, dict):
            raise UnrecognizedFormatError(
                "Genie returned a non-dictionary show interfaces status result",
                parser_id=cls._descriptor.parser_id,
            )
        raw_interfaces = parsed.get("interfaces")
        if not isinstance(raw_interfaces, dict) or not raw_interfaces:
            raise UnrecognizedFormatError(
                "Genie did not identify any show interfaces status rows",
                parser_id=cls._descriptor.parser_id,
            )

        interfaces: GenieInterfaces = {}
        for interface, values in raw_interfaces.items():
            if not isinstance(interface, str) or not isinstance(values, dict):
                raise UnrecognizedFormatError(
                    "Genie returned an invalid interfaces container",
                    parser_id=cls._descriptor.parser_id,
                )
            normalized_values: GenieInterfaceValues = {}
            for key, value in values.items():
                if not isinstance(key, str):
                    raise UnrecognizedFormatError(
                        f"Genie returned a non-string field for interface {interface!r}",
                        parser_id=cls._descriptor.parser_id,
                    )
                normalized_values[key] = value
            interfaces[interface] = normalized_values

        if not callable(converter):
            raise GenieDependencyError(
                "Genie Common.convert_intf_name is unavailable",
                parser_id=cls._descriptor.parser_id,
            )

        def convert_intf_name(raw_interface: str) -> str:
            try:
                converted: Any = converter(raw_interface)
            except Exception as exc:
                raise GenieExtractionError(
                    f"Genie failed to canonicalize RAW interface {raw_interface!r}",
                    parser_id=cls._descriptor.parser_id,
                ) from exc
            if not isinstance(converted, str) or not converted.strip():
                raise GenieExtractionError(
                    f"Genie returned an invalid canonical interface for {raw_interface!r}",
                    parser_id=cls._descriptor.parser_id,
                )
            return converted

        return interfaces, convert_intf_name

    @staticmethod
    def _index_raw_rows(
        content: str,
        convert_intf_name: InterfaceNameConverter,
    ) -> tuple[_RawInterfaceRow, ...]:
        rows: list[_RawInterfaceRow] = []
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or _STATUS_TOKEN_RE.search(stripped) is None:
                continue
            raw_interface = stripped.split(maxsplit=1)[0]
            rows.append(
                _RawInterfaceRow(
                    canonical_interface=convert_intf_name(raw_interface),
                    line_number=line_number,
                    raw_interface=raw_interface,
                )
            )
        return tuple(rows)

    @staticmethod
    def _group_raw_rows(
        raw_rows: tuple[_RawInterfaceRow, ...],
    ) -> dict[str, tuple[_RawInterfaceRow, ...]]:
        grouped: dict[str, list[_RawInterfaceRow]] = {}
        for row in raw_rows:
            grouped.setdefault(row.canonical_interface, []).append(row)
        return {interface: tuple(rows) for interface, rows in grouped.items()}

    @staticmethod
    def _build_consistency_warnings(
        *,
        raw_rows: tuple[_RawInterfaceRow, ...],
        rows_by_interface: dict[str, tuple[_RawInterfaceRow, ...]],
        genie_interfaces: GenieInterfaces,
    ) -> list[ParserWarning]:
        warnings: list[ParserWarning] = []

        for interface, rows in rows_by_interface.items():
            if len(rows) > 1:
                warnings.append(
                    ParserWarning(
                        code="duplicate_raw_interface_row",
                        message=(
                            f"RAW contains {len(rows)} candidate rows for {interface!r} "
                            f"at lines {', '.join(str(row.line_number) for row in rows)}."
                        ),
                        field="interfaces",
                    )
                )

        for row in raw_rows:
            if row.canonical_interface not in genie_interfaces:
                warnings.append(
                    ParserWarning(
                        code="genie_unparsed_interface",
                        message=(
                            f"RAW interface row {row.raw_interface!r} at line {row.line_number} "
                            "was not returned by Genie."
                        ),
                        field="interfaces",
                    )
                )

        for interface in sorted(genie_interfaces):
            source_rows = rows_by_interface.get(interface, ())
            if len(source_rows) != 1:
                warnings.append(
                    ParserWarning(
                        code="genie_source_line_not_unique",
                        message=(
                            f"Genie returned {interface!r}, but the framework found "
                            f"{len(source_rows)} candidate RAW source rows."
                        ),
                        field="interfaces",
                    )
                )

        if len(raw_rows) != len(genie_interfaces):
            warnings.append(
                ParserWarning(
                    code="genie_interface_count_mismatch",
                    message=(
                        f"RAW candidate rows={len(raw_rows)}; "
                        f"Genie interfaces={len(genie_interfaces)}."
                    ),
                    field="interfaces",
                )
            )

        return warnings

    @staticmethod
    def _ordered_genie_items(
        genie_interfaces: GenieInterfaces,
        rows_by_interface: dict[str, tuple[_RawInterfaceRow, ...]],
    ) -> tuple[tuple[str, GenieInterfaceValues], ...]:
        def order_key(item: tuple[str, GenieInterfaceValues]) -> tuple[int, str]:
            interface, _ = item
            source_rows = rows_by_interface.get(interface, ())
            first_line = source_rows[0].line_number if source_rows else 2**31 - 1
            return first_line, interface

        return tuple(sorted(genie_interfaces.items(), key=order_key))

    @classmethod
    def _adapt_record(
        cls,
        *,
        ordinal: int,
        interface: str,
        values: GenieInterfaceValues,
    ) -> InterfaceStatusRecord:
        status = cls._required_genie_text(values, "status", interface)
        vlan = cls._required_genie_text(values, "vlan", interface)
        duplex = cls._required_genie_text(values, "duplex_code", interface)
        speed = cls._required_genie_text(values, "port_speed", interface)
        description = cls._optional_genie_text(values, "name", interface)
        media_type = cls._optional_genie_text(values, "type", interface)

        try:
            return InterfaceStatusRecord(
                ordinal=ordinal,
                interface=interface,
                description=description,
                status=status,
                vlan=vlan,
                duplex=duplex,
                speed=speed,
                media_type=media_type,
            )
        except ValidationError as exc:
            raise UnrecognizedFormatError(
                f"Genie returned invalid normalized data for interface {interface!r}",
                parser_id=cls._descriptor.parser_id,
            ) from exc

    @classmethod
    def _required_genie_text(
        cls,
        values: GenieInterfaceValues,
        key: str,
        interface: str,
    ) -> str:
        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            raise UnrecognizedFormatError(
                f"Genie returned missing or invalid {key!r} for interface {interface!r}",
                parser_id=cls._descriptor.parser_id,
            )
        return value

    @classmethod
    def _optional_genie_text(
        cls,
        values: GenieInterfaceValues,
        key: str,
        interface: str,
    ) -> str | None:
        value = values.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise UnrecognizedFormatError(
                f"Genie returned invalid optional {key!r} for interface {interface!r}",
                parser_id=cls._descriptor.parser_id,
            )
        return value

    @staticmethod
    def _field_evidence(
        *,
        index: int,
        record: InterfaceStatusRecord,
        line_number: int,
    ) -> list[FieldEvidence]:
        prefix = f"interfaces[{index}]"
        evidence_fields = [
            prefix,
            f"{prefix}.ordinal",
            f"{prefix}.interface",
            f"{prefix}.status",
            f"{prefix}.vlan",
            f"{prefix}.duplex",
            f"{prefix}.speed",
        ]
        if record.description is not None:
            evidence_fields.append(f"{prefix}.description")
        if record.media_type is not None:
            evidence_fields.append(f"{prefix}.media_type")

        return [
            FieldEvidence(
                field=field,
                extractor=_EXTRACTOR,
                line_start=line_number,
                line_end=line_number,
            )
            for field in evidence_fields
        ]
