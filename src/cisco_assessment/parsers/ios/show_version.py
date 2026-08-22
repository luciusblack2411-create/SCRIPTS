"""IOS/IOS-XE ``show version`` parser."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import DeviceInfo

from ..base import BaseParser
from ..errors import UnrecognizedFormatError
from ..models import FieldEvidence, ParsedPayload, ParserDescriptor, ParserWarning


@dataclass(frozen=True, slots=True)
class _LineMatch:
    line_number: int
    extractor: str
    match: re.Match[str]


class IOSShowVersionParser(BaseParser[DeviceInfo]):
    """Normalize IOS and IOS-XE ``show version`` output into ``DeviceInfo``."""

    _descriptor = ParserDescriptor(
        parser_id=ParserId.IOS_SHOW_VERSION_V1,
        parser_version="0.1.0",
        command_id=CommandId.SYSTEM_VERSION,
        normalized_model=NormalizedModelId.DEVICE_INFO,
        supported_platforms=frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE}),
    )

    @property
    def descriptor(self) -> ParserDescriptor:
        return self._descriptor

    def _parse_content(
        self,
        content: str,
        platform: PlatformFamily,
    ) -> ParsedPayload[DeviceInfo]:
        # This is a working view only. RawCommandOutput.content remains untouched.
        lines = content.replace("\r\n", "\n").replace("\r", "\n").splitlines()

        warnings: list[ParserWarning] = []
        evidence: list[FieldEvidence] = []

        detected_platform = self._detect_platform(lines)
        normalized_platform = detected_platform or platform
        if detected_platform is not None and detected_platform != platform:
            warnings.append(
                ParserWarning(
                    code="platform_mismatch",
                    message=(
                        f"Collector platform is {platform.value}, while show version "
                        f"looks like {detected_platform.value}."
                    ),
                    field="platform",
                )
            )

        version_hit = self._first_match(
            lines,
            (
                (
                    "iosxe_version_header",
                    re.compile(
                        r"Cisco IOS XE Software,\s*Version\s+(?P<value>[^,\s]+)",
                        re.IGNORECASE,
                    ),
                ),
                (
                    "ios_version_header",
                    re.compile(
                        r"Cisco IOS Software.*?\bVersion\s+(?P<value>[^,\s]+)",
                        re.IGNORECASE,
                    ),
                ),
            ),
        )
        if version_hit is None:
            raise UnrecognizedFormatError(
                "Unable to identify Cisco IOS/IOS-XE software version",
                parser_id=self.descriptor.parser_id,
            )
        software_version = version_hit.match.group("value")
        evidence.append(self._evidence("software_version", version_hit))

        uptime_hit = self._first_match(
            lines,
            (
                (
                    "uptime_line",
                    re.compile(
                        r"^(?P<hostname>\S+)\s+uptime is\s+(?P<uptime>.+)$",
                        re.IGNORECASE,
                    ),
                ),
            ),
        )
        hostname: str | None = None
        uptime_text: str | None = None
        if uptime_hit is None:
            warnings.append(
                ParserWarning(
                    code="hostname_uptime_not_found",
                    message="Hostname and uptime could not be extracted from show version.",
                )
            )
        else:
            hostname = uptime_hit.match.group("hostname")
            uptime_text = uptime_hit.match.group("uptime")
            evidence.append(self._evidence("hostname", uptime_hit))
            evidence.append(self._evidence("uptime_text", uptime_hit))

        image_hit = self._first_match(
            lines,
            (
                (
                    "system_image",
                    re.compile(
                        r'System image file is\s+"?(?P<value>[^"\s]+)"?',
                        re.IGNORECASE,
                    ),
                ),
            ),
        )
        system_image = self._optional_value(
            image_hit,
            field="system_image",
            warning_code="system_image_not_found",
            warnings=warnings,
            evidence=evidence,
        )

        serial_hit = self._first_match(
            lines,
            (
                (
                    "processor_board_id",
                    re.compile(r"Processor board ID\s+(?P<value>\S+)", re.IGNORECASE),
                ),
                (
                    "system_serial_number",
                    re.compile(
                        r"System Serial Number\s*:\s*(?P<value>\S+)",
                        re.IGNORECASE,
                    ),
                ),
            ),
        )
        serial_number = self._optional_value(
            serial_hit,
            field="serial_number",
            warning_code="serial_number_not_found",
            warnings=warnings,
            evidence=evidence,
        )

        model_hit = self._first_match(
            lines,
            (
                (
                    "model_number",
                    re.compile(r"Model Number\s*:\s*(?P<value>\S+)", re.IGNORECASE),
                ),
                (
                    "processor_model",
                    re.compile(
                        r"^cisco\s+(?P<value>\S+)\s+\(.+\)\s+processor\b",
                        re.IGNORECASE,
                    ),
                ),
            ),
        )
        model = self._optional_value(
            model_hit,
            field="model",
            warning_code="model_not_found",
            warnings=warnings,
            evidence=evidence,
        )

        boot_hit = self._first_match(
            lines,
            (
                (
                    "switch_table_mode",
                    re.compile(
                        r"^\s*\*?\s*\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+"
                        r"(?P<value>INSTALL|BUNDLE)\s*$",
                        re.IGNORECASE,
                    ),
                ),
            ),
        )
        boot_mode = None
        if boot_hit is not None:
            boot_mode = boot_hit.match.group("value").upper()
            evidence.append(self._evidence("boot_mode", boot_hit))

        return ParsedPayload(
            data=DeviceInfo(
                platform=normalized_platform,
                hostname=hostname,
                software_version=software_version,
                model=model,
                serial_number=serial_number,
                system_image=system_image,
                uptime_text=uptime_text,
                boot_mode=boot_mode,
            ),
            warnings=tuple(warnings),
            evidence=tuple(evidence),
        )

    @staticmethod
    def _detect_platform(lines: list[str]) -> PlatformFamily | None:
        for line in lines:
            upper = line.upper()
            if "CISCO IOS XE SOFTWARE" in upper or "IOS-XE SOFTWARE" in upper:
                return PlatformFamily.IOS_XE
        for line in lines:
            if "CISCO IOS SOFTWARE" in line.upper():
                return PlatformFamily.IOS
        return None

    @staticmethod
    def _first_match(
        lines: list[str],
        patterns: tuple[tuple[str, re.Pattern[str]], ...],
    ) -> _LineMatch | None:
        for line_number, line in enumerate(lines, start=1):
            for extractor, pattern in patterns:
                match = pattern.search(line)
                if match is not None:
                    return _LineMatch(
                        line_number=line_number,
                        extractor=extractor,
                        match=match,
                    )
        return None

    @staticmethod
    def _evidence(field: str, hit: _LineMatch) -> FieldEvidence:
        return FieldEvidence(
            field=field,
            extractor=hit.extractor,
            line_start=hit.line_number,
            line_end=hit.line_number,
        )

    def _optional_value(
        self,
        hit: _LineMatch | None,
        *,
        field: str,
        warning_code: str,
        warnings: list[ParserWarning],
        evidence: list[FieldEvidence],
    ) -> str | None:
        if hit is None:
            warnings.append(
                ParserWarning(
                    code=warning_code,
                    message=f"{field} could not be extracted from show version.",
                    field=field,
                )
            )
            return None

        evidence.append(self._evidence(field, hit))
        return hit.match.group("value")
