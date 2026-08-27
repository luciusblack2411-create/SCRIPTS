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
_NAME_RE = re.compile(r"^\s*Name:\s*(?P<value>\S(?:.*\S)?)\s*$")
_LABEL_RE = re.compile(r"^\s*(?P<label>[^:]+):\s*(?P<value>.*?)\s*$")
_VLAN_CONTINUATION_RE = re.compile(r"^\s*(?P<value>[0-9][0-9,\-\s]*)\s*$")

_LABEL_FIELDS = {
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
class _ObservedBlock:
    interface: str
    name_line: int
    values: dict[str, str] = field(default_factory=dict)
    source_lines: dict[str, tuple[int, int]] = field(default_factory=dict)


class IOSShowInterfacesSwitchportParser(BaseParser[SwitchportObservation]):
    """Normalize authoritative switchport Name blocks without consulting other domains."""

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

    def _parse_content(
        self,
        content: str,
        platform: PlatformFamily,
    ) -> ParsedPayload[SwitchportObservation]:
        lines = self._build_parsing_lines(content)
        blocks: list[_ObservedBlock] = []
        current: _ObservedBlock | None = None
        seen_interfaces: set[str] = set()

        for line in lines:
            name_match = _NAME_RE.fullmatch(line.text)
            if name_match is not None:
                interface = name_match.group("value").strip()
                if interface in seen_interfaces:
                    raise UnrecognizedFormatError(
                        f"Duplicate interface Name block {interface!r}",
                        parser_id=self.descriptor.parser_id,
                    )
                current = _ObservedBlock(interface=interface, name_line=line.raw_line_number)
                blocks.append(current)
                seen_interfaces.add(interface)
                continue

            if current is None:
                continue

            label_match = _LABEL_RE.fullmatch(line.text)
            if label_match is not None:
                field_name = _LABEL_FIELDS.get(label_match.group("label").strip())
                if field_name is not None:
                    value = label_match.group("value").strip()
                    if value:
                        current.values[field_name] = value
                        current.source_lines[field_name] = (
                            line.raw_line_number,
                            line.raw_line_number,
                        )
                    continue

            if "allowed_vlans" not in current.values:
                continue
            start, end = current.source_lines["allowed_vlans"]
            if end != line.raw_line_number - 1:
                continue
            continuation = _VLAN_CONTINUATION_RE.fullmatch(line.text)
            if continuation is None:
                continue
            value = continuation.group("value").replace(" ", "")
            if not value:
                continue
            current.values["allowed_vlans"] += value
            current.source_lines["allowed_vlans"] = (start, line.raw_line_number)

        if not blocks:
            raise UnrecognizedFormatError(
                "Unable to identify any IOS/IOS-XE show interfaces switchport Name blocks",
                parser_id=self.descriptor.parser_id,
            )

        warnings: list[ParserWarning] = []
        records: list[SwitchportRecord] = []
        evidence: list[FieldEvidence] = []

        for index, block in enumerate(blocks):
            switchport_enabled = self._normalize_boolean(
                block.values.get("switchport_enabled"),
                true_token="Enabled",
                false_token="Disabled",
                warning_code="switchport_state_unrecognized",
                warning_field=f"interfaces[{index}].switchport_enabled",
                line_number=self._line_for(block, "switchport_enabled"),
                warnings=warnings,
            )
            negotiation = self._normalize_boolean(
                block.values.get("negotiation_of_trunking"),
                true_token="On",
                false_token="Off",
                warning_code="trunk_negotiation_unrecognized",
                warning_field=f"interfaces[{index}].negotiation_of_trunking",
                line_number=self._line_for(block, "negotiation_of_trunking"),
                warnings=warnings,
            )

            try:
                record = SwitchportRecord(
                    ordinal=index + 1,
                    interface=block.interface,
                    switchport_enabled=switchport_enabled,
                    administrative_mode=block.values.get("administrative_mode"),
                    operational_mode=block.values.get("operational_mode"),
                    access_vlan=block.values.get("access_vlan"),
                    native_vlan=block.values.get("native_vlan"),
                    allowed_vlans=block.values.get("allowed_vlans"),
                    voice_vlan=block.values.get("voice_vlan"),
                    negotiation_of_trunking=negotiation,
                )
            except ValidationError as exc:
                raise UnrecognizedFormatError(
                    f"Interface {block.interface!r} cannot satisfy SwitchportRecord v0.1",
                    parser_id=self.descriptor.parser_id,
                ) from exc

            records.append(record)
            evidence.extend(self._evidence_for_block(index, block))

        evidence.insert(
            0,
            FieldEvidence(
                field="interfaces",
                extractor=_EXTRACTOR,
                line_start=blocks[0].name_line,
                line_end=max(
                    (end for block in blocks for _, end in block.source_lines.values()),
                    default=blocks[-1].name_line,
                ),
            ),
        )

        try:
            observation = SwitchportObservation(platform=platform, interfaces=tuple(records))
        except ValidationError as exc:
            raise UnrecognizedFormatError(
                "Parsed Name blocks cannot satisfy SwitchportObservation v0.1",
                parser_id=self.descriptor.parser_id,
            ) from exc

        return ParsedPayload(
            data=observation,
            warnings=tuple(warnings),
            evidence=tuple(evidence),
        )

    @staticmethod
    def _line_for(block: _ObservedBlock, field_name: str) -> int | None:
        source = block.source_lines.get(field_name)
        return None if source is None else source[0]

    @staticmethod
    def _normalize_boolean(
        value: str | None,
        *,
        true_token: str,
        false_token: str,
        warning_code: str,
        warning_field: str,
        line_number: int | None,
        warnings: list[ParserWarning],
    ) -> bool | None:
        if value is None:
            return None
        if value == true_token:
            return True
        if value == false_token:
            return False
        location = "" if line_number is None else f" at line {line_number}"
        warnings.append(
            ParserWarning(
                code=warning_code,
                message=(
                    f"Unrecognized token {value!r}{location}; the normalized value is unknown."
                ),
                field=warning_field,
            )
        )
        return None

    @staticmethod
    def _evidence_for_block(index: int, block: _ObservedBlock) -> list[FieldEvidence]:
        prefix = f"interfaces[{index}]"
        items = [
            FieldEvidence(
                field=f"{prefix}.ordinal",
                extractor=_EXTRACTOR,
                line_start=block.name_line,
                line_end=block.name_line,
            ),
            FieldEvidence(
                field=f"{prefix}.interface",
                extractor=_EXTRACTOR,
                line_start=block.name_line,
                line_end=block.name_line,
            ),
        ]
        for field_name, (line_start, line_end) in block.source_lines.items():
            items.append(
                FieldEvidence(
                    field=f"{prefix}.{field_name}",
                    extractor=(
                        _EXTRACTOR_CONTINUATION
                        if field_name == "allowed_vlans" and line_end > line_start
                        else _EXTRACTOR
                    ),
                    line_start=line_start,
                    line_end=line_end,
                )
            )
        return items

    @classmethod
    def _build_parsing_lines(cls, content: str) -> tuple[_ParsingLine, ...]:
        """Build a terminal-rendered view while retaining every RAW logical line number."""
        raw_lines = content.replace("\r\n", "\n").split("\n")
        return tuple(
            _ParsingLine(number, cls._render_terminal_line(raw_line))
            for number, raw_line in enumerate(raw_lines, start=1)
        )

    @staticmethod
    def _render_terminal_line(raw_line: str) -> str:
        """Render cursor artifacts in parser-local state; never mutate source RAW."""
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
