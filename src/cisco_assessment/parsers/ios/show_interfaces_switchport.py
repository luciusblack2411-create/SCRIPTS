"""Deterministic IOS/IOS-XE ``show interfaces switchport`` parser."""

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
_NAME_RE = re.compile(r"^\s*Name:\s*(?P<value>\S.*?)\s*$")
_FIELD_RE = re.compile(
    r"^\s*(?P<label>Switchport|Administrative Mode|Operational Mode|"
    r"Access Mode VLAN|Trunking Native Mode VLAN|Trunking VLANs Enabled|"
    r"Voice VLAN|Negotiation of Trunking):\s*(?P<value>.*?)\s*$"
)
_VLAN_CONTINUATION_RE = re.compile(r"^[0-9,\-\s]+$")
_EXTRACTOR = "show_interfaces_switchport_labels"
_EXTRACTOR_ALLOWED = "show_interfaces_switchport_allowed_vlans"

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


@dataclass(frozen=True, slots=True)
class _ParsingLine:
    raw_line_number: int
    text: str


@dataclass(slots=True)
class _ObservedBlock:
    interface: str
    name_line: int
    values: dict[str, str] = field(default_factory=dict)
    ranges: dict[str, tuple[int, int]] = field(default_factory=dict)


class IOSShowInterfacesSwitchportParser(BaseParser[SwitchportObservation]):
    """Normalize only facts demonstrated by authoritative Name blocks."""

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
        seen_interfaces: set[str] = set()
        current: _ObservedBlock | None = None
        allowed_can_continue = False

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
                allowed_can_continue = False
                continue

            field_match = _FIELD_RE.fullmatch(line.text)
            if field_match is not None:
                allowed_can_continue = False
                if current is None:
                    continue
                label = field_match.group("label")
                value = field_match.group("value").strip()
                field_name = _LABEL_FIELDS[label]
                if value:
                    current.values[field_name] = value
                    current.ranges[field_name] = (
                        line.raw_line_number,
                        line.raw_line_number,
                    )
                    allowed_can_continue = field_name == "allowed_vlans"
                continue

            stripped = line.text.strip()
            if (
                current is not None
                and allowed_can_continue
                and stripped
                and any(character.isdigit() for character in stripped)
                and _VLAN_CONTINUATION_RE.fullmatch(stripped) is not None
            ):
                prior = current.values["allowed_vlans"].rstrip()
                continuation = re.sub(r"\s+", "", stripped)
                current.values["allowed_vlans"] = prior + continuation
                start, _ = current.ranges["allowed_vlans"]
                current.ranges["allowed_vlans"] = (start, line.raw_line_number)
                continue

            allowed_can_continue = False

        if not blocks:
            raise UnrecognizedFormatError(
                "Unable to identify any IOS/IOS-XE show interfaces switchport Name blocks",
                parser_id=self.descriptor.parser_id,
            )

        records: list[SwitchportRecord] = []
        warnings: list[ParserWarning] = []
        evidence: list[FieldEvidence] = []

        for index, block in enumerate(blocks):
            switchport = self._normalize_boolean(
                block.values.get("switchport_enabled"),
                true_token="Enabled",
                false_token="Disabled",
                warning_code="switchport_state_unrecognized",
                warning_label="Switchport",
                field_name=f"interfaces[{index}].switchport_enabled",
                warnings=warnings,
            )
            negotiation = self._normalize_boolean(
                block.values.get("negotiation_of_trunking"),
                true_token="On",
                false_token="Off",
                warning_code="trunk_negotiation_unrecognized",
                warning_label="Negotiation of Trunking",
                field_name=f"interfaces[{index}].negotiation_of_trunking",
                warnings=warnings,
            )
            try:
                record = SwitchportRecord(
                    ordinal=index + 1,
                    interface=block.interface,
                    switchport_enabled=switchport,
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
            evidence.extend(self._block_evidence(index, block))

        try:
            observation = SwitchportObservation(platform=platform, interfaces=tuple(records))
        except ValidationError as exc:
            raise UnrecognizedFormatError(
                "Parsed Name blocks cannot satisfy SwitchportObservation v0.1",
                parser_id=self.descriptor.parser_id,
            ) from exc

        evidence.insert(
            0,
            FieldEvidence(
                field="interfaces",
                extractor=_EXTRACTOR,
                line_start=blocks[0].name_line,
                line_end=max(
                    max((line_end for _, line_end in block.ranges.values()), default=block.name_line)
                    for block in blocks
                ),
            ),
        )
        return ParsedPayload(
            data=observation,
            warnings=tuple(warnings),
            evidence=tuple(evidence),
        )

    @staticmethod
    def _normalize_boolean(
        value: str | None,
        *,
        true_token: str,
        false_token: str,
        warning_code: str,
        warning_label: str,
        field_name: str,
        warnings: list[ParserWarning],
    ) -> bool | None:
        if value is None:
            return None
        if value == true_token:
            return True
        if value == false_token:
            return False
        warnings.append(
            ParserWarning(
                code=warning_code,
                message=f"Unrecognized {warning_label} token {value!r}; normalized value is None.",
                field=field_name,
            )
        )
        return None

    @staticmethod
    def _block_evidence(index: int, block: _ObservedBlock) -> list[FieldEvidence]:
        prefix = f"interfaces[{index}]"
        result = [
            FieldEvidence(prefix, _EXTRACTOR, block.name_line, block.name_line),
            FieldEvidence(f"{prefix}.ordinal", _EXTRACTOR, block.name_line, block.name_line),
            FieldEvidence(f"{prefix}.interface", _EXTRACTOR, block.name_line, block.name_line),
        ]
        for field_name, (line_start, line_end) in block.ranges.items():
            extractor = _EXTRACTOR_ALLOWED if field_name == "allowed_vlans" else _EXTRACTOR
            result.append(
                FieldEvidence(
                    field=f"{prefix}.{field_name}",
                    extractor=extractor,
                    line_start=line_start,
                    line_end=line_end,
                )
            )
        return result

    @classmethod
    def _build_parsing_lines(cls, content: str) -> tuple[_ParsingLine, ...]:
        raw_lines = content.replace("\r\n", "\n").split("\n")
        return tuple(
            _ParsingLine(number, cls._render_terminal_line(raw_line))
            for number, raw_line in enumerate(raw_lines, start=1)
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
        return _PAGER_PREFIX_RE.sub("", "".join(cells), count=1)
