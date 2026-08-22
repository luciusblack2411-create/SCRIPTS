"""IOS/IOS-XE ``show inventory`` parser."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import (
    HardwareComponent,
    HardwareComponentKind,
    HardwareInventory,
)

from ..base import BaseParser
from ..errors import UnrecognizedFormatError
from ..models import FieldEvidence, ParsedPayload, ParserDescriptor, ParserWarning

_NAME_RE = re.compile(r'^NAME:\s*"(?P<name>[^"]+)"\s*,\s*DESCR:\s*"(?P<descr>[^"]*)"\s*$')
_PID_RE = re.compile(
    r"^PID:\s*(?P<pid>[^,]*?)\s*,\s*VID:\s*(?P<vid>[^,]*?)\s*,\s*SN:\s*(?P<sn>.*?)\s*$"
)
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PAGER_PREFIX_RE = re.compile(r"^\s*--More--\s*")


@dataclass(frozen=True, slots=True)
class _ParsingLine:
    """Derived terminal view mapped one-to-one to a RAW logical line."""

    raw_line_number: int
    text: str


@dataclass(frozen=True, slots=True)
class _Record:
    component: HardwareComponent
    start_line: int
    end_line: int


class IOSShowInventoryParser(BaseParser[HardwareInventory]):
    """Normalize IOS/IOS-XE ``show inventory`` output."""

    _descriptor = ParserDescriptor(
        parser_id=ParserId.IOS_SHOW_INVENTORY_V1,
        parser_version="0.1.0",
        command_id=CommandId.SYSTEM_INVENTORY,
        normalized_model=NormalizedModelId.HARDWARE_INVENTORY,
        supported_platforms=frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE}),
    )

    @property
    def descriptor(self) -> ParserDescriptor:
        return self._descriptor

    def _parse_content(
        self,
        content: str,
        platform: PlatformFamily,
    ) -> ParsedPayload[HardwareInventory]:
        lines = self._build_parsing_lines(content)
        records: list[_Record] = []
        warnings: list[ParserWarning] = []

        index = 0
        while index < len(lines):
            name_match = _NAME_RE.match(lines[index].text.strip())
            if name_match is None:
                index += 1
                continue

            pid_index = index + 1
            while pid_index < len(lines) and not lines[pid_index].text.strip():
                pid_index += 1
            if pid_index >= len(lines):
                warnings.append(
                    ParserWarning(
                        code="inventory_record_incomplete",
                        message=(
                            f"Inventory record at line {lines[index].raw_line_number} "
                            "has no PID/VID/SN line."
                        ),
                    )
                )
                break

            pid_match = _PID_RE.match(lines[pid_index].text.strip())
            if pid_match is None:
                warnings.append(
                    ParserWarning(
                        code="inventory_record_incomplete",
                        message=(
                            f"Inventory record at line {lines[index].raw_line_number} "
                            "has an unrecognized PID/VID/SN line."
                        ),
                    )
                )
                index = pid_index + 1
                continue

            name = name_match.group("name").strip()
            description = self._clean(name_match.group("descr"))
            pid = self._clean(pid_match.group("pid"))
            vid = self._clean(pid_match.group("vid"))
            serial = self._clean(pid_match.group("sn"))
            kind = self._classify(name=name, description=description)
            records.append(
                _Record(
                    component=HardwareComponent(
                        name=name,
                        description=description,
                        pid=pid,
                        vid=vid,
                        serial_number=serial,
                        kind=kind,
                    ),
                    start_line=lines[index].raw_line_number,
                    end_line=lines[pid_index].raw_line_number,
                )
            )
            index = pid_index + 1

        if not records:
            raise UnrecognizedFormatError(
                "Unable to identify any IOS/IOS-XE show inventory records",
                parser_id=self.descriptor.parser_id,
            )

        chassis_record = next(
            (record for record in records if record.component.kind == HardwareComponentKind.CHASSIS),
            records[0],
        )
        chassis = chassis_record.component.model_copy(update={"kind": HardwareComponentKind.CHASSIS})

        modules: list[HardwareComponent] = []
        components: list[HardwareComponent] = []
        for record in records:
            if record is chassis_record:
                continue
            if record.component.kind == HardwareComponentKind.MODULE:
                modules.append(record.component)
            else:
                components.append(record.component)

        evidence = [
            FieldEvidence(
                field="chassis",
                extractor="inventory_record",
                line_start=chassis_record.start_line,
                line_end=chassis_record.end_line,
            ),
            FieldEvidence(
                field="chassis.pid",
                extractor="pid_vid_sn",
                line_start=chassis_record.end_line,
                line_end=chassis_record.end_line,
            ),
            FieldEvidence(
                field="chassis.serial_number",
                extractor="pid_vid_sn",
                line_start=chassis_record.end_line,
                line_end=chassis_record.end_line,
            ),
        ]
        if modules:
            module_lines = [
                record for record in records if record.component.kind == HardwareComponentKind.MODULE
            ]
            evidence.append(
                FieldEvidence(
                    field="modules",
                    extractor="inventory_records",
                    line_start=min(record.start_line for record in module_lines),
                    line_end=max(record.end_line for record in module_lines),
                )
            )
        if components:
            component_records = [
                record
                for record in records
                if record is not chassis_record
                and record.component.kind != HardwareComponentKind.MODULE
            ]
            evidence.append(
                FieldEvidence(
                    field="components",
                    extractor="inventory_records",
                    line_start=min(record.start_line for record in component_records),
                    line_end=max(record.end_line for record in component_records),
                )
            )

        return ParsedPayload(
            data=HardwareInventory(
                platform=platform,
                chassis=chassis,
                modules=tuple(modules),
                components=tuple(components),
            ),
            warnings=tuple(warnings),
            evidence=tuple(evidence),
        )

    @classmethod
    def _build_parsing_lines(cls, content: str) -> tuple[_ParsingLine, ...]:
        """Build a terminal-rendered view without changing or dropping RAW lines.

        Cisco pagination can leave ``--More--`` plus cursor-control bytes in the
        byte-exact evidence. Parsing uses this derived view only; line numbers stay
        aligned with the original CRLF/LF-delimited RAW for FieldEvidence.
        """
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
        """Render only terminal artifacts needed to recognize inventory records."""
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

    @staticmethod
    def _clean(value: str) -> str | None:
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _classify(*, name: str, description: str | None) -> HardwareComponentKind:
        text = f"{name} {description or ''}".casefold()
        if any(token in text for token in ("chassis", "system", "switch")):
            return HardwareComponentKind.CHASSIS
        if any(token in text for token in ("module", "supervisor", "linecard", "line card")):
            return HardwareComponentKind.MODULE
        return HardwareComponentKind.COMPONENT
