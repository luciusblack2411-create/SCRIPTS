"""IOS/IOS-XE ``show vlan brief`` parser."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.vlan import VlanObservation, VlanRecord, VlanStatus

from ..base import BaseParser
from ..errors import UnrecognizedFormatError
from ..models import FieldEvidence, ParsedPayload, ParserDescriptor, ParserWarning

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PAGER_PREFIX_RE = re.compile(r"^\s*--More--\s*")
_HEADER_RE = re.compile(r"^VLAN\s+Name\s+Status\s+Ports\s*$")
_SEPARATOR_RE = re.compile(r"^-+\s+-+\s+-+\s+-+\s*$")
_PROMPT_RE = re.compile(r"^\S+[>#]\s*$")
_COMMAND_ECHO = "show vlan brief"
_PORT_SEPARATOR = ","
_EXTRACTOR_COLUMNS = "show_vlan_brief_columns"
_EXTRACTOR_PORTS = "show_vlan_brief_ports"

_STATUS_MAP: dict[str, VlanStatus] = {
    "active": VlanStatus.ACTIVE,
    "suspend": VlanStatus.SUSPENDED,
    "suspended": VlanStatus.SUSPENDED,
    "act/unsup": VlanStatus.ACTIVE_UNSUPPORTED,
}


@dataclass(frozen=True, slots=True)
class _ParsingLine:
    """Terminal-rendered parser view mapped one-to-one to a RAW logical line."""

    raw_line_number: int
    text: str


@dataclass(frozen=True, slots=True)
class _ColumnLayout:
    name_start: int
    status_start: int
    ports_start: int


@dataclass(slots=True)
class _ObservedVlan:
    vlan_id: int
    name: str | None
    status: VlanStatus
    status_raw: str
    ports: list[str]
    start_line: int
    port_source_lines: list[int]


class IOSShowVlanBriefParser(BaseParser[VlanObservation]):
    """Normalize authoritative ``show vlan brief`` output into VlanObservation v0.1."""

    _descriptor = ParserDescriptor(
        parser_id=ParserId.IOS_SHOW_VLAN_BRIEF_V1,
        parser_version="0.1.0",
        command_id=CommandId.VLANS_BRIEF,
        normalized_model=NormalizedModelId.VLAN_OBSERVATION,
        supported_platforms=frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE}),
    )

    @property
    def descriptor(self) -> ParserDescriptor:
        return self._descriptor

    def _parse_content(
        self,
        content: str,
        platform: PlatformFamily,
    ) -> ParsedPayload[VlanObservation]:
        lines = self._build_parsing_lines(content)
        layout: _ColumnLayout | None = None
        observed: list[_ObservedVlan] = []
        warnings: list[ParserWarning] = []
        current: _ObservedVlan | None = None
        seen_vlan_ids: set[int] = set()

        for line in lines:
            stripped = line.text.strip()

            detected_layout = self._detect_layout(line.text)
            if detected_layout is not None:
                if layout is None:
                    layout = detected_layout
                elif layout != detected_layout:
                    warnings.append(
                        ParserWarning(
                            code="vlan_header_layout_changed",
                            message=(
                                f"VLAN table header at line {line.raw_line_number} changed "
                                "column positions."
                            ),
                            field="vlans",
                        )
                    )
                    layout = detected_layout
                continue

            if layout is None:
                continue

            if (
                not stripped
                or _SEPARATOR_RE.fullmatch(stripped) is not None
                or stripped == _COMMAND_ECHO
                or _PROMPT_RE.fullmatch(stripped) is not None
            ):
                continue

            padded = line.text.ljust(layout.ports_start)
            vlan_cell = padded[: layout.name_start].strip()
            port_cell = (
                line.text[layout.ports_start :].strip()
                if len(line.text) > layout.ports_start
                else ""
            )

            if not vlan_cell and not padded[: layout.ports_start].strip() and port_cell:
                if current is None:
                    warnings.append(
                        ParserWarning(
                            code="orphan_vlan_ports_continuation",
                            message=(
                                f"Ports continuation at line {line.raw_line_number} "
                                "cannot be associated with a VLAN row."
                            ),
                            field="vlans",
                        )
                    )
                    continue
                ports = self._split_ports(
                    port_cell,
                    line_number=line.raw_line_number,
                    warnings=warnings,
                )
                self._append_ports(
                    current,
                    ports=ports,
                    line_number=line.raw_line_number,
                    warnings=warnings,
                )
                continue

            if vlan_cell.isdigit():
                vlan_id = int(vlan_cell)
                if vlan_id in seen_vlan_ids:
                    warnings.append(
                        ParserWarning(
                            code="duplicate_vlan_row",
                            message=(
                                f"Duplicate VLAN ID {vlan_id} at line "
                                f"{line.raw_line_number}; the first observed row is retained."
                            ),
                            field="vlans",
                        )
                    )
                    current = None
                    continue

                name = padded[layout.name_start : layout.status_start].strip() or None
                status_raw = padded[layout.status_start : layout.ports_start].strip()
                status = self._normalize_status(
                    status_raw,
                    line_number=line.raw_line_number,
                    warnings=warnings,
                )
                ports = self._split_ports(
                    port_cell,
                    line_number=line.raw_line_number,
                    warnings=warnings,
                )

                current = _ObservedVlan(
                    vlan_id=vlan_id,
                    name=name,
                    status=status,
                    status_raw=status_raw,
                    ports=[],
                    start_line=line.raw_line_number,
                    port_source_lines=[],
                )
                self._append_ports(
                    current,
                    ports=ports,
                    line_number=line.raw_line_number,
                    warnings=warnings,
                )
                observed.append(current)
                seen_vlan_ids.add(vlan_id)
                continue

            if line.text[:1].isdigit():
                warnings.append(
                    ParserWarning(
                        code="unparsed_vlan_row",
                        message=f"Unrecognized VLAN row at line {line.raw_line_number}.",
                        field="vlans",
                    )
                )

        if layout is None:
            raise UnrecognizedFormatError(
                "Unable to identify the IOS/IOS-XE show vlan brief table header",
                parser_id=self.descriptor.parser_id,
            )
        if not observed:
            raise UnrecognizedFormatError(
                "Unable to identify any IOS/IOS-XE show vlan brief VLAN rows",
                parser_id=self.descriptor.parser_id,
            )

        records: list[VlanRecord] = []
        evidence: list[FieldEvidence] = []

        for index, item in enumerate(observed):
            try:
                record = VlanRecord(
                    ordinal=index + 1,
                    vlan_id=item.vlan_id,
                    name=item.name,
                    status=item.status,
                    ports=tuple(item.ports),
                )
            except ValidationError as exc:
                raise UnrecognizedFormatError(
                    f"Observed VLAN {item.vlan_id} cannot satisfy VlanRecord v0.1",
                    parser_id=self.descriptor.parser_id,
                ) from exc

            records.append(record)
            evidence.extend(self._field_evidence(index=index, item=item, record=record))

        evidence.insert(
            0,
            FieldEvidence(
                field="vlans",
                extractor=_EXTRACTOR_COLUMNS,
                line_start=min(item.start_line for item in observed),
                line_end=max(
                    item.port_source_lines[-1] if item.port_source_lines else item.start_line
                    for item in observed
                ),
            ),
        )

        try:
            observation = VlanObservation(platform=platform, vlans=tuple(records))
        except ValidationError as exc:
            raise UnrecognizedFormatError(
                "Parsed VLAN rows cannot satisfy VlanObservation v0.1",
                parser_id=self.descriptor.parser_id,
            ) from exc

        return ParsedPayload(
            data=observation,
            warnings=tuple(warnings),
            evidence=tuple(evidence),
        )

    @staticmethod
    def _detect_layout(line: str) -> _ColumnLayout | None:
        if _HEADER_RE.fullmatch(line.strip()) is None:
            return None
        try:
            return _ColumnLayout(
                name_start=line.index("Name"),
                status_start=line.index("Status"),
                ports_start=line.index("Ports"),
            )
        except ValueError:
            return None

    @staticmethod
    def _normalize_status(
        raw_status: str,
        *,
        line_number: int,
        warnings: list[ParserWarning],
    ) -> VlanStatus:
        normalized = raw_status.strip().lower()
        if not normalized:
            warnings.append(
                ParserWarning(
                    code="vlan_status_missing",
                    message=f"VLAN row at line {line_number} has no demonstrable status.",
                    field="vlans",
                )
            )
            return VlanStatus.UNKNOWN

        status = _STATUS_MAP.get(normalized)
        if status is not None:
            return status

        warnings.append(
            ParserWarning(
                code="vlan_status_unrecognized",
                message=(
                    f"VLAN row at line {line_number} has unrecognized status "
                    f"{raw_status!r}; normalized status is unknown."
                ),
                field="vlans",
            )
        )
        return VlanStatus.UNKNOWN

    @staticmethod
    def _split_ports(
        port_cell: str,
        *,
        line_number: int,
        warnings: list[ParserWarning],
    ) -> tuple[str, ...]:
        if not port_cell:
            return ()

        ports = tuple(part.strip() for part in port_cell.split(_PORT_SEPARATOR) if part.strip())
        if not ports:
            warnings.append(
                ParserWarning(
                    code="vlan_ports_unparsed",
                    message=f"Unable to identify ports at line {line_number}.",
                    field="vlans",
                )
            )
        return ports

    @staticmethod
    def _append_ports(
        item: _ObservedVlan,
        *,
        ports: tuple[str, ...],
        line_number: int,
        warnings: list[ParserWarning],
    ) -> None:
        if not ports:
            return

        existing = set(item.ports)
        for port in ports:
            if port in existing:
                warnings.append(
                    ParserWarning(
                        code="duplicate_vlan_port",
                        message=(
                            f"VLAN {item.vlan_id} repeats port {port!r} at line "
                            f"{line_number}; the first occurrence is retained."
                        ),
                        field="vlans",
                    )
                )
                continue
            item.ports.append(port)
            existing.add(port)

        item.port_source_lines.append(line_number)

    @staticmethod
    def _field_evidence(
        *,
        index: int,
        item: _ObservedVlan,
        record: VlanRecord,
    ) -> list[FieldEvidence]:
        prefix = f"vlans[{index}]"
        evidence = [
            FieldEvidence(
                field=f"{prefix}.vlan_id",
                extractor=_EXTRACTOR_COLUMNS,
                line_start=item.start_line,
                line_end=item.start_line,
            )
        ]

        if record.name is not None:
            evidence.append(
                FieldEvidence(
                    field=f"{prefix}.name",
                    extractor=_EXTRACTOR_COLUMNS,
                    line_start=item.start_line,
                    line_end=item.start_line,
                )
            )

        if item.status_raw:
            evidence.append(
                FieldEvidence(
                    field=f"{prefix}.status",
                    extractor=_EXTRACTOR_COLUMNS,
                    line_start=item.start_line,
                    line_end=item.start_line,
                )
            )

        if record.ports is not None:
            if item.port_source_lines:
                port_start = item.port_source_lines[0]
                port_end = item.port_source_lines[-1]
            else:
                port_start = port_end = item.start_line
            evidence.append(
                FieldEvidence(
                    field=f"{prefix}.ports",
                    extractor=_EXTRACTOR_PORTS,
                    line_start=port_start,
                    line_end=port_end,
                )
            )

        return evidence

    @classmethod
    def _build_parsing_lines(cls, content: str) -> tuple[_ParsingLine, ...]:
        """Build a terminal-rendered view without changing or dropping RAW lines."""
        raw_lines = content.replace("\r\n", "\n").split("\n")
        return tuple(
            _ParsingLine(
                raw_line_number=line_number,
                text=cls._render_terminal_line(raw_line),
            )
            for line_number, raw_line in enumerate(raw_lines, start=1)
        )

    @staticmethod
    def _render_terminal_line(raw_line: str) -> str:
        """Render pager/cursor artifacts only in parser-local derived state."""
        line = _ANSI_CSI_RE.sub("", raw_line)
        cells: list[str] = []
        cursor = 0

        for character in line:
            if character == "\x08":
                cursor = max(0, cursor - 1)
                continue
            if character == "\r":
                cursor = 0
                continue
            if character in {"\x00", "\x07", "\x7f"}:
                continue
            if ord(character) < 32:
                continue

            if cursor < len(cells):
                cells[cursor] = character
            else:
                if cursor > len(cells):
                    cells.extend(" " * (cursor - len(cells)))
                cells.append(character)
            cursor += 1

        rendered = "".join(cells)
        return _PAGER_PREFIX_RE.sub("", rendered, count=1)
