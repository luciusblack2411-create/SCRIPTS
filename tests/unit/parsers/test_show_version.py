from pathlib import Path
from uuid import uuid4

import pytest

from cisco_assessment.catalog.enums import CommandId, ParserId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.parsers import (
    EmptyRawOutputError,
    IOSShowVersionParser,
    ParseStatus,
    TraceabilityMismatchError,
    UnrecognizedFormatError,
    UnsupportedPlatformError,
    build_parser_registry,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "ios" / "show_version"


def _execution() -> CommandExecution:
    return CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.SYSTEM_VERSION.value,
        command="show version",
        sequence=1,
    )


def _raw(
    execution: CommandExecution,
    content: str,
    *,
    is_truncated: bool = False,
) -> RawCommandOutput:
    return RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content=content,
        is_truncated=is_truncated,
    )


def test_parse_iosxe_show_version_preserves_traceability() -> None:
    execution = _execution()
    content = (FIXTURES / "c9300_iosxe.txt").read_text(encoding="utf-8")
    raw = _raw(execution, content)
    parser = IOSShowVersionParser()

    result = parser.parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.SUCCESS
    assert result.data.hostname == "SW-CORE-01"
    assert result.data.platform is PlatformFamily.IOS_XE
    assert result.data.software_version == "17.09.04a"
    assert result.data.model == "C9300-48P"
    assert result.data.serial_number == "FCW0000A1B2"
    assert result.data.system_image == "flash:packages.conf"
    assert result.data.boot_mode == "INSTALL"
    assert result.trace.command_execution_id == execution.id
    assert result.trace.raw_output_id == raw.id
    assert result.trace.raw_sha256 == raw.sha256
    assert result.trace.parser_id is ParserId.IOS_SHOW_VERSION_V1
    assert any(item.field == "software_version" for item in result.evidence)
    assert raw.content == content


def test_parse_classic_ios_show_version() -> None:
    execution = _execution()
    content = (FIXTURES / "c2960x_ios.txt").read_text(encoding="utf-8")
    raw = _raw(execution, content)

    result = IOSShowVersionParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS,
    )

    assert result.status is ParseStatus.SUCCESS
    assert result.data.hostname == "SW-ACCESS-01"
    assert result.data.platform is PlatformFamily.IOS
    assert result.data.software_version == "15.2(7)E7"
    assert result.data.model == "WS-C2960X-48FPD-L"
    assert result.data.serial_number == "FOC0000A1B2"
    assert result.data.boot_mode is None


def test_missing_optional_fields_returns_partial_result() -> None:
    execution = _execution()
    raw = _raw(
        execution,
        "Cisco IOS XE Software, Version 17.12.04\nSW-LAB uptime is 2 days\n",
    )

    result = IOSShowVersionParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.PARTIAL
    assert result.data.hostname == "SW-LAB"
    assert {warning.code for warning in result.warnings} == {
        "model_not_found",
        "serial_number_not_found",
        "system_image_not_found",
    }


def test_truncated_raw_is_explicitly_partial() -> None:
    execution = _execution()
    content = (FIXTURES / "c9300_iosxe.txt").read_text(encoding="utf-8")
    raw = _raw(execution, content, is_truncated=True)

    result = IOSShowVersionParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.PARTIAL
    assert any(warning.code == "raw_truncated" for warning in result.warnings)


def test_empty_raw_raises_typed_error() -> None:
    execution = _execution()
    raw = _raw(execution, "   \n")

    with pytest.raises(EmptyRawOutputError):
        IOSShowVersionParser().parse(
            raw_output=raw,
            command_execution=execution,
            platform=PlatformFamily.IOS_XE,
        )


def test_unrecognized_format_raises_typed_error() -> None:
    execution = _execution()
    raw = _raw(execution, "not a Cisco show version output\n")

    with pytest.raises(UnrecognizedFormatError) as exc_info:
        IOSShowVersionParser().parse(
            raw_output=raw,
            command_execution=execution,
            platform=PlatformFamily.IOS,
        )

    assert exc_info.value.command_execution_id == execution.id
    assert exc_info.value.raw_output_id == raw.id


def test_traceability_mismatch_is_rejected() -> None:
    execution = _execution()
    other_execution = _execution()
    raw = _raw(other_execution, "Cisco IOS XE Software, Version 17.09.04a\n")

    with pytest.raises(TraceabilityMismatchError) as exc_info:
        IOSShowVersionParser().parse(
            raw_output=raw,
            command_execution=execution,
            platform=PlatformFamily.IOS_XE,
        )

    assert exc_info.value.command_execution_id == execution.id
    assert exc_info.value.raw_output_id == raw.id


def test_registry_resolves_ios_and_iosxe_but_not_nxos() -> None:
    registry = build_parser_registry()

    assert (
        registry.resolve(ParserId.IOS_SHOW_VERSION_V1, PlatformFamily.IOS).descriptor.parser_id
        is ParserId.IOS_SHOW_VERSION_V1
    )
    assert (
        registry.resolve(ParserId.IOS_SHOW_VERSION_V1, PlatformFamily.IOS_XE).descriptor.parser_id
        is ParserId.IOS_SHOW_VERSION_V1
    )

    with pytest.raises(UnsupportedPlatformError):
        registry.resolve(ParserId.IOS_SHOW_VERSION_V1, PlatformFamily.NX_OS)
