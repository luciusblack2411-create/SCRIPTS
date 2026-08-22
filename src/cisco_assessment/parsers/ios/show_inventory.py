"""IOS/IOS-XE ``show inventory`` parser."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import (
    HardwareComponentType,
    HardwareInventory,
    HardwareInventoryRecord,
    hardware_inventory_record_id,
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
_SWITCH_MEMBER_RE = re.compile(r"^Switch\s+(?P<member>\d+)$", re.IGNORECASE)
_SWITCH_PREFIX_RE = re.compile(r"^Switch\s+(?P<member>\d+)\b", re.IGNORECASE)
_STACK_PORT_RE = re.compile(r"^StackPort(?P<member>\d+)/(?P<endpoint>\d+)$", re.IGNORECASE)
_INTERFACE_MEMBER_RE = re.compile(
    r"^(?:Gi|Te|Tw|Fo|Hu|Eth|Ethernet|GigabitEthernet|TenGigabitEthernet|"
    r"TwentyFiveGigE|FortyGigabitEthernet|HundredGigE)"
    r"(?P<member>\d+)/\d+/\d+$",
    re.IGNORECASE,
)
_POWER_SUPPLY_MEMBER_RE = re.compile(
    r"^Power\s+Supply\s+Module\s+\d+/(?P<member>\d+)$",
    re.IGNORECASE,
)
_NETWORK_MODULE_MEMBER_RE = re.compile(
    r"^Network\s+Module\s+\d+/(?P<member>\d+)$",
    re.IGNORECASE,
)
_FAN_MEMBER_RE = re.compile(
    r"^Fan(?:\s+Tray|\s+Module)?\s+\d+/(?P<member>\d+)$",
    re.IGNORECASE,
)
_STACK_ADAPTER_MEMBER_RE = re.compile(
    r"^Stack\s*Adapter(?P<member>\d+)(?:/\d+)?$",
    re.IGNORECASE,
)
_NETWORK_MODULE_PID_RE = re.compile(r"(?:^|-)NM(?:-|$)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _ParsingLine:
    """Derived terminal view mapped one-to-one to a RAW logical line."""

    raw_line_number: int
    text: str


@dataclass(frozen=True, slots=True)
class _ObservedRecord:
    ordinal: int
    name: str
    description: str | None
    pid: str | None
    vid: str | None
    serial_number: str | None
    component_type: HardwareComponentType
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class _Record:
    record: HardwareInventoryRecord
    start_line: int
    end_line: int


class IOSShowInventoryParser(BaseParser[HardwareInventory]):
    """Normalize IOS/IOS-XE ``show inventory`` output into HardwareInventory v0.2."""

    _descriptor = ParserDescriptor(
        parser_id=ParserId.IOS_SHOW_INVENTORY_V1,
        parser_version="0.2.0",
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
        observed: list[_ObservedRecord] = []
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
            serial_number = self._clean(pid_match.group("sn"))
            observed.append(
                _ObservedRecord(
                    ordinal=len(observed) + 1,
                    name=name,
                    description=description,
                    pid=pid,
                    vid=vid,
                    serial_number=serial_number,
                    component_type=self._classify(
                        name=name,
                        description=description,
                        pid=pid,
                    ),
                    start_line=lines[index].raw_line_number,
                    end_line=lines[pid_index].raw_line_number,
                )
            )
            index = pid_index + 1

        if not observed:
            raise UnrecognizedFormatError(
                "Unable to identify any IOS/IOS-XE show inventory records",
                parser_id=self.descriptor.parser_id,
            )

        member_ids = self._build_unique_member_id_map(observed)
        records = tuple(
            _Record(
                record=HardwareInventoryRecord(
                    ordinal=item.ordinal,
                    name=item.name,
                    description=item.description,
                    pid=item.pid,
                    vid=item.vid,
                    serial_number=item.serial_number,
                    component_type=item.component_type,
                    parent_id=self._resolve_parent_id(item, member_ids),
                ),
                start_line=item.start_line,
                end_line=item.end_line,
            )
            for item in observed
        )
        evidence = self._build_evidence(records)

        return ParsedPayload(
            data=HardwareInventory(
                platform=platform,
                records=tuple(item.record for item in records),
            ),
            warnings=tuple(warnings),
            evidence=tuple(evidence),
        )

    @staticmethod
    def _build_unique_member_id_map(records: list[_ObservedRecord]) -> dict[int, str]:
        candidates: dict[int, list[str]] = {}
        for item in records:
            if item.component_type is not HardwareComponentType.CHASSIS_MEMBER:
                continue
            match = _SWITCH_MEMBER_RE.fullmatch(item.name)
            if match is None:
                continue
            member = int(match.group("member"))
            candidates.setdefault(member, []).append(hardware_inventory_record_id(item.ordinal))

        return {
            member: ids[0]
            for member, ids in candidates.items()
            if len(ids) == 1
        }

    @classmethod
    def _resolve_parent_id(
        cls,
        record: _ObservedRecord,
        member_ids: dict[int, str],
    ) -> str | None:
        if record.component_type is HardwareComponentType.CHASSIS_MEMBER:
            return None

        member = cls._explicit_parent_member(record)
        if member is None:
            return None
        return member_ids.get(member)

    @staticmethod
    def _explicit_parent_member(record: _ObservedRecord) -> int | None:
        switch_prefix = _SWITCH_PREFIX_RE.match(record.name)
        if switch_prefix is not None:
            return int(switch_prefix.group("member"))

        pattern: re.Pattern[str] | None = None
        if record.component_type is HardwareComponentType.STACK_CABLE_ENDPOINT:
            pattern = _STACK_PORT_RE
        elif record.component_type is HardwareComponentType.TRANSCEIVER:
            pattern = _INTERFACE_MEMBER_RE
        elif record.component_type is HardwareComponentType.POWER_SUPPLY:
            pattern = _POWER_SUPPLY_MEMBER_RE
        elif record.component_type is HardwareComponentType.NETWORK_MODULE:
            pattern = _NETWORK_MODULE_MEMBER_RE
        elif record.component_type is HardwareComponentType.FAN:
            pattern = _FAN_MEMBER_RE
        elif record.component_type is HardwareComponentType.STACK_ADAPTER:
            pattern = _STACK_ADAPTER_MEMBER_RE

        if pattern is None:
            return None
        match = pattern.fullmatch(record.name)
        if match is None:
            return None
        return int(match.group("member"))

    @staticmethod
    def _classify(
        *,
        name: str,
        description: str | None,
        pid: str | None,
    ) -> HardwareComponentType:
        name_folded = name.casefold()
        description_folded = (description or "").casefold()
        pid_upper = (pid or "").upper()
        combined = f"{name_folded} {description_folded}"

        if _SWITCH_MEMBER_RE.fullmatch(name) is not None or name_folded == "chassis":
            return HardwareComponentType.CHASSIS_MEMBER
        if _STACK_PORT_RE.fullmatch(name) is not None:
            return HardwareComponentType.STACK_CABLE_ENDPOINT
        if "power supply" in combined or pid_upper.startswith("PWR-"):
            return HardwareComponentType.POWER_SUPPLY
        if (
            "transceiver" in combined
            or "sfp" in description_folded
            or "qsfp" in description_folded
            or pid_upper.startswith(("GLC-", "SFP-", "QSFP-", "X2-", "XFP-"))
        ):
            return HardwareComponentType.TRANSCEIVER
        if (
            "stack adapter" in combined
            or "stackadapter" in combined
            or "STACK-ADPT" in pid_upper
            or "STACK-ADAPTER" in pid_upper
        ):
            return HardwareComponentType.STACK_ADAPTER
        if (
            "network module" in combined
            or "uplink module" in combined
            or _NETWORK_MODULE_PID_RE.search(pid_upper) is not None
        ):
            return HardwareComponentType.NETWORK_MODULE
        if "fan" in combined or pid_upper.endswith("-FAN"):
            return HardwareComponentType.FAN
        return HardwareComponentType.OTHER

    @staticmethod
    def _build_evidence(records: tuple[_Record, ...]) -> list[FieldEvidence]:
        evidence: list[FieldEvidence] = [
            FieldEvidence(
                field="records",
                extractor="inventory_records",
                line_start=min(item.start_line for item in records),
                line_end=max(item.end_line for item in records),
            )
        ]

        for index, item in enumerate(records):
            field = f"records[{index}]"
            evidence.append(
                FieldEvidence(
                    field=field,
                    extractor="inventory_record",
                    line_start=item.start_line,
                    line_end=item.end_line,
                )
            )
            evidence.append(
                FieldEvidence(
                    field=f"{field}.name",
                    extractor="name_descr",
                    line_start=item.start_line,
                    line_end=item.start_line,
                )
            )
            if item.record.description is not None:
                evidence.append(
                    FieldEvidence(
                        field=f"{field}.description",
                        extractor="name_descr",
                        line_start=item.start_line,
                        line_end=item.start_line,
                    )
                )
            for attribute in ("pid", "vid", "serial_number"):
                if getattr(item.record, attribute) is None:
                    continue
                evidence.append(
                    FieldEvidence(
                        field=f"{field}.{attribute}",
                        extractor="pid_vid_sn",
                        line_start=item.end_line,
                        line_end=item.end_line,
                    )
                )
            evidence.append(
                FieldEvidence(
                    field=f"{field}.component_type",
                    extractor="inventory_classification_patterns",
                    line_start=item.start_line,
                    line_end=item.end_line,
                )
            )
            if item.record.parent_id is not None:
                evidence.append(
                    FieldEvidence(
                        field=f"{field}.parent_id",
                        extractor="explicit_member_name_pattern",
                        line_start=item.start_line,
                        line_end=item.start_line,
                    )
                )

        IOSShowInventoryParser._append_legacy_evidence(evidence, records)
        return evidence

    @staticmethod
    def _append_legacy_evidence(
        evidence: list[FieldEvidence],
        records: tuple[_Record, ...],
    ) -> None:
        first_member = next(
            (
                item
                for item in records
                if item.record.component_type is HardwareComponentType.CHASSIS_MEMBER
            ),
            None,
        )
        if first_member is not None:
            evidence.extend(
                (
                    FieldEvidence(
                        field="chassis",
                        extractor="inventory_record",
                        line_start=first_member.start_line,
                        line_end=first_member.end_line,
                    ),
                    FieldEvidence(
                        field="chassis.pid",
                        extractor="pid_vid_sn",
                        line_start=first_member.end_line,
                        line_end=first_member.end_line,
                    ),
                    FieldEvidence(
                        field="chassis.serial_number",
                        extractor="pid_vid_sn",
                        line_start=first_member.end_line,
                        line_end=first_member.end_line,
                    ),
                )
            )

        modules = tuple(
            item
            for item in records
            if item.record.component_type is HardwareComponentType.NETWORK_MODULE
        )
        if modules:
            evidence.append(
                FieldEvidence(
                    field="modules",
                    extractor="inventory_records",
                    line_start=min(item.start_line for item in modules),
                    line_end=max(item.end_line for item in modules),
                )
            )

        first_member_id = None if first_member is None else first_member.record.id
        components = tuple(
            item
            for item in records
            if item.record.id != first_member_id
            and item.record.component_type is not HardwareComponentType.NETWORK_MODULE
        )
        if components:
            evidence.append(
                FieldEvidence(
                    field="components",
                    extractor="inventory_records",
                    line_start=min(item.start_line for item in components),
                    line_end=max(item.end_line for item in components),
                )
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
