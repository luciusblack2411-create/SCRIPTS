"""IOS/IOS-XE ``show interfaces status`` Genie extraction spike."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.interface import InterfaceObservation, InterfaceStatusRecord

from ..base import BaseParser
from ..errors import UnrecognizedFormatError
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


@dataclass(frozen=True, slots=True)
class _RawInterfaceRow:
    canonical_interface: str
    line_number: int
    raw_interface: str


class IOSShowInterfacesStatusParser(BaseParser[InterfaceObservation]):
    """Use Genie only for extraction, then adapt into framework-owned models."""

    _descriptor = ParserDescriptor(
        parser_id=ParserId.IOS_SHOW_INTERFACES_STATUS_V1,
        parser_version="0.1.0-spike",
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
        genie_output, convert_intf_name = self._extract_with_genie(content, platform)
        genie_interfaces = genie_output.get("interfaces")
        if not isinstance(genie_interfaces, dict) or not genie_interfaces:
            raise UnrecognizedFormatError(
                "Genie did not identify any show interfaces status rows",
                parser_id=self.descriptor.parser_id,
            )

        raw_rows = self._index_raw_rows(content, convert_intf_name)
        rows_by_interface: dict[str, list[_RawInterfaceRow]] = {}
        for row in raw_rows:
            rows_by_interface.setdefault(row.canonical_interface, []).append(row)

        warnings: list[ParserWarning] = []
        raw_names = set(rows_by_interface)
        genie_names = set(genie_interfaces)
        for interface in sorted(raw_names - genie_names):
            row = rows_by_interface[interface][0]
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
        for interface in sorted(genie_names - raw_names):
            warnings.append(
                ParserWarning(
                    code="genie_source_line_not_found",
                    message=f"Genie returned {interface!r} but no unique RAW source row was found.",
                    field="interfaces",
                )
            )
        for interface, rows in sorted(rows_by_interface.items()):
            if len(rows) > 1:
                warnings.append(
                    ParserWarning(
                        code="duplicate_raw_interface_row",
                        message=f"RAW contains {len(rows)} candidate rows for {interface!r}.",
                        field="interfaces",
                    )
                )

        records: list[InterfaceStatusRecord] = []
        evidence: list[FieldEvidence] = []
        source_line_numbers: list[int] = []

        for index, (interface, values) in enumerate(genie_interfaces.items()):
            if not isinstance(interface, str) or not isinstance(values, dict):
                continue
            record = self._adapt_record(interface, values)
            records.append(record)

            source_rows = rows_by_interface.get(interface, [])
            if len(source_rows) != 1:
                continue
            source_line = source_rows[0].line_number
            source_line_numbers.append(source_line)
            evidence.extend(self._field_evidence(index, record, source_line))

        if not records:
            raise UnrecognizedFormatError(
                "Genie returned an interfaces container without usable records",
                parser_id=self.descriptor.parser_id,
            )

        if source_line_numbers:
            evidence.insert(
                0,
                FieldEvidence(
                    field="interfaces",
                    extractor="genie_show_interfaces_status+raw_line_index",
                    line_start=min(source_line_numbers),
                    line_end=max(source_line_numbers),
                ),
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

        return ParsedPayload(
            data=InterfaceObservation(platform=platform, interfaces=tuple(records)),
            warnings=tuple(warnings),
            evidence=tuple(evidence),
        )

    def extract_genie_structure(
        self,
        content: str,
        platform: PlatformFamily = PlatformFamily.IOS_XE,
    ) -> dict[str, Any]:
        """Expose the spike's raw Genie structure for characterization tests only."""
        output, _ = self._extract_with_genie(content, platform)
        return output

    @staticmethod
    def _extract_with_genie(
        content: str,
        platform: PlatformFamily,
    ) -> tuple[dict[str, Any], Any]:
        try:
            if platform is PlatformFamily.IOS:
                from genie.libs.parser.ios.show_interface import (  # type: ignore[import-not-found]
                    ShowInterfacesStatus as GenieShowInterfacesStatus,
                )
            else:
                from genie.libs.parser.iosxe.show_interface import (  # type: ignore[import-not-found]
                    ShowInterfacesStatus as GenieShowInterfacesStatus,
                )
            from genie.libs.parser.utils.common import Common  # type: ignore[import-not-found]
        except ImportError as exc:
            raise UnrecognizedFormatError(
                "Genie spike dependencies are not installed; install the isolated spike requirements"
            ) from exc

        parser = GenieShowInterfacesStatus(device=None)
        parsed = parser.cli(output=content)
        if not isinstance(parsed, dict):
            raise UnrecognizedFormatError("Genie returned a non-dictionary result")
        return parsed, Common.convert_intf_name

    @staticmethod
    def _index_raw_rows(content: str, convert_intf_name: Any) -> tuple[_RawInterfaceRow, ...]:
        rows: list[_RawInterfaceRow] = []
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or _STATUS_TOKEN_RE.search(stripped) is None:
                continue
            raw_interface = stripped.split(maxsplit=1)[0]
            canonical = convert_intf_name(raw_interface)
            rows.append(
                _RawInterfaceRow(
                    canonical_interface=canonical,
                    line_number=line_number,
                    raw_interface=raw_interface,
                )
            )
        return tuple(rows)

    @staticmethod
    def _adapt_record(interface: str, values: dict[str, Any]) -> InterfaceStatusRecord:
        required = ("status", "vlan", "duplex_code", "port_speed")
        if any(not isinstance(values.get(key), str) for key in required):
            raise UnrecognizedFormatError(
                f"Genie returned incomplete data for interface {interface!r}"
            )
        name = values.get("name")
        media_type = values.get("type")
        return InterfaceStatusRecord(
            interface=interface,
            description=name if isinstance(name, str) else None,
            status=values["status"],
            vlan=values["vlan"],
            duplex=values["duplex_code"],
            speed=values["port_speed"],
            media_type=media_type if isinstance(media_type, str) else None,
        )

    @staticmethod
    def _field_evidence(
        index: int,
        record: InterfaceStatusRecord,
        line_number: int,
    ) -> list[FieldEvidence]:
        prefix = f"interfaces[{index}]"
        fields = ["interface", "status", "vlan", "duplex", "speed"]
        if record.description is not None:
            fields.append("description")
        if record.media_type is not None:
            fields.append("media_type")
        return [
            FieldEvidence(
                field=f"{prefix}.{field}",
                extractor="genie_show_interfaces_status+raw_line_index",
                line_start=line_number,
                line_end=line_number,
            )
            for field in fields
        ]
