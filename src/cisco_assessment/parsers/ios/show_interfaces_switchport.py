"""IOS/IOS-XE ``show interfaces switchport`` parser."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.switchport import SwitchportObservation, SwitchportRecord

from ..base import BaseParser
from ..errors import UnrecognizedFormatError
from ..models import FieldEvidence, ParsedPayload, ParserDescriptor, ParserWarning

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PAGER_PREFIX_RE = re.compile(r"^\s*--More--\s*")
_NAME_RE = re.compile(r"^\s*Name:\s*(\S.*?)\s*$")
_LABEL_RE = re.compile(r"^\s*([^:]+):\s*(.*?)\s*$")
_VLAN_CONTINUATION_RE = re.compile(r"^\s*([0-9]+(?:[-,][0-9]+)*)\s*$")
_LABELS = {
    "Switchport": "switchport_enabled",
    "Administrative Mode": "administrative_mode",
    "Operational Mode": "operational_mode",
    "Access Mode VLAN": "access_vlan",
    "Trunking Native Mode VLAN": "native_vlan",
    "Trunking VLANs Enabled": "allowed_vlans",
    "Voice VLAN": "voice_vlan",
    "Negotiation of Trunking": "negotiation_of_trunking",
}
_EXTRACTOR = "show_interfaces_switchport_labels"
_EXTRACTOR_CONTINUATION = "show_interfaces_switchport_vlan_continuation"


@dataclass(frozen=True, slots=True)
class _ParsingLine:
    raw_line_number: int
    text: str


@dataclass(slots=True)
class _ObservedInterface:
    interface: str
    name_line: int
    values: dict[str, str] = field(default_factory=dict)
    source_lines: dict[str, list[int]] = field(default_factory=dict)


class IOSShowInterfacesSwitchportParser(BaseParser[SwitchportObservation]):
    """Normalize authoritative switchport Name blocks without inference."""

    _descriptor = ParserDescriptor(
        parser_id=ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1,
        parser_version="0.1.0",
        command_id=CommandId.INTERFACES_SWITCHPORT,
        normalized_model=NormalizedModelId.SWITCHPORT_OBSERVATION,
        supported_platforms=frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE}),
    )

    @property
    def descriptor(self) -> ParserDescriptor:
        return self._descriptor

    def _parse_content(self, content: str, platform: PlatformFamily) -> ParsedPayload[SwitchportObservation]:
        observed: list[_ObservedInterface] = []
        seen: set[str] = set()
        current: _ObservedInterface | None = None
        for line in self._build_parsing_lines(content):
            name_match = _NAME_RE.fullmatch(line.text)
            if name_match is not None:
                interface = name_match.group(1).strip()
                if interface in seen:
                    raise UnrecognizedFormatError(
                        f"Duplicate interface Name block {interface!r}",
                        parser_id=self.descriptor.parser_id,
                    )
                current = _ObservedInterface(interface, line.raw_line_number)
                observed.append(current)
                seen.add(interface)
                continue
            if current is None:
                continue
            label_match = _LABEL_RE.fullmatch(line.text)
            if label_match is not None:
                field_name = _LABELS.get(label_match.group(1).strip())
                if field_name is not None:
                    raw_value = label_match.group(2).strip()
                    if raw_value:
                        current.values[field_name] = raw_value
                        current.source_lines[field_name] = [line.raw_line_number]
                    continue
            allowed_lines = current.source_lines.get("allowed_vlans")
            if allowed_lines and allowed_lines[-1] == line.raw_line_number - 1:
                continuation = _VLAN_CONTINUATION_RE.fullmatch(line.text)
                if continuation is not None:
                    current.values["allowed_vlans"] += continuation.group(1)
                    allowed_lines.append(line.raw_line_number)
        if not observed:
            raise UnrecognizedFormatError(
                "Unable to identify show interfaces switchport Name blocks",
                parser_id=self.descriptor.parser_id,
            )

        records: list[SwitchportRecord] = []
        evidence: list[FieldEvidence] = []
        warnings: list[ParserWarning] = []
        for index, item in enumerate(observed):
            switchport = self._boolean(item, "switchport_enabled", "Enabled", "Disabled", "switchport_state_unrecognized", index, warnings)
            negotiation = self._boolean(item, "negotiation_of_trunking", "On", "Off", "trunk_negotiation_unrecognized", index, warnings)
            try:
                record = SwitchportRecord(
                    ordinal=index + 1,
                    interface=item.interface,
                    switchport_enabled=switchport,
                    administrative_mode=item.values.get("administrative_mode"),
                    operational_mode=item.values.get("operational_mode"),
                    access_vlan=item.values.get("access_vlan"),
                    native_vlan=item.values.get("native_vlan"),
                    allowed_vlans=item.values.get("allowed_vlans"),
                    voice_vlan=item.values.get("voice_vlan"),
                    negotiation_of_trunking=negotiation,
                )
            except ValidationError as exc:
                raise UnrecognizedFormatError(
                    f"Interface {item.interface!r} cannot satisfy SwitchportRecord v0.1",
                    parser_id=self.descriptor.parser_id,
                ) from exc
            records.append(record)
            evidence.extend(self._field_evidence(index, item, record))
        try:
            data = SwitchportObservation(platform=platform, interfaces=tuple(records))
        except ValidationError as exc:
            raise UnrecognizedFormatError(
                "Parsed Name blocks cannot satisfy SwitchportObservation v0.1",
                parser_id=self.descriptor.parser_id,
            ) from exc
        return ParsedPayload(data=data, warnings=tuple(warnings), evidence=tuple(evidence))

    @staticmethod
    def _boolean(item: _ObservedInterface, name: str, true_token: str, false_token: str, warning_code: str, index: int, warnings: list[ParserWarning]) -> bool | None:
        raw = item.values.get(name)
        if raw is None:
            return None
        if raw == true_token:
            return True
        if raw == false_token:
            return False
        line = item.source_lines[name][0]
        warnings.append(ParserWarning(
            code=warning_code,
            message=f"Unrecognized value {raw!r} at line {line}; normalized value is unknown.",
            field=f"interfaces[{index}].{name}",
        ))
        return None

    @staticmethod
    def _field_evidence(index: int, item: _ObservedInterface, record: SwitchportRecord) -> list[FieldEvidence]:
        prefix = f"interfaces[{index}]"
        result = [FieldEvidence(field=f"{prefix}.interface", extractor=_EXTRACTOR, line_start=item.name_line, line_end=item.name_line)]
        values = {
            "switchport_enabled": record.switchport_enabled,
            "administrative_mode": record.administrative_mode,
            "operational_mode": record.operational_mode,
            "access_vlan": record.access_vlan,
            "native_vlan": record.native_vlan,
            "allowed_vlans": record.allowed_vlans,
            "voice_vlan": record.voice_vlan,
            "negotiation_of_trunking": record.negotiation_of_trunking,
        }
        for name, value in values.items():
            lines = item.source_lines.get(name)
            if value is None or not lines:
                continue
            result.append(FieldEvidence(
                field=f"{prefix}.{name}",
                extractor=_EXTRACTOR_CONTINUATION if name == "allowed_vlans" and len(lines) > 1 else _EXTRACTOR,
                line_start=lines[0],
                line_end=lines[-1],
            ))
        return result

    @classmethod
    def _build_parsing_lines(cls, content: str) -> tuple[_ParsingLine, ...]:
        return tuple(
            _ParsingLine(number, cls._render_terminal_line(raw_line))
            for number, raw_line in enumerate(content.replace("\r\n", "\n").split("\n"), start=1)
        )

    @staticmethod
    def _render_terminal_line(raw_line: str) -> str:
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
            if character in {"\x00", "\x07", "\x7f"} or ord(character) < 32:
                continue
            if cursor < len(cells):
                cells[cursor] = character
            else:
                if cursor > len(cells):
                    cells.extend(" " * (cursor - len(cells)))
                cells.append(character)
            cursor += 1
        return _PAGER_PREFIX_RE.sub("", "".join(cells), count=1)
