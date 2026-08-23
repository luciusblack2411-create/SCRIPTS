from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import cisco_assessment.parsers.ios.show_interfaces_status as parser_module
from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models import CommandExecution, InterfaceObservation, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.parsers import (
    GenieDependencyError,
    GenieExtractionError,
    IOSShowInterfacesStatusParser,
    ParseStatus,
    UnsupportedPlatformError,
    build_parser_registry,
)

FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "ios"
    / "show_interfaces_status"
    / "c9300_iosxe_genie_v0_1.txt"
)

_EXPECTED_INTERFACES = [
    "GigabitEthernet1/0/1",
    "GigabitEthernet1/0/2",
    "GigabitEthernet1/0/3",
    "GigabitEthernet1/0/4",
    "GigabitEthernet1/0/47",
    "TenGigabitEthernet1/1/1",
    "Port-channel10",
]


def _execution() -> CommandExecution:
    return CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.INTERFACES_STATUS.value,
        command="show interfaces status",
        sequence=1,
    )


def _parse_content(
    content: str,
    *,
    platform: PlatformFamily = PlatformFamily.IOS_XE,
) -> tuple[CommandExecution, RawCommandOutput, object]:
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)
    result = IOSShowInterfacesStatusParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=platform,
    )
    return execution, raw, result


def _fake_convert(raw_interface: str) -> str:
    prefixes = {
        "Gi": "GigabitEthernet",
        "Te": "TenGigabitEthernet",
        "Po": "Port-channel",
    }
    for short, long_name in prefixes.items():
        if raw_interface.startswith(short):
            return long_name + raw_interface[len(short) :]
    return raw_interface


def _genie_values(
    *,
    status: str = "connected",
    vlan: str = "10",
    duplex: str = "a-full",
    speed: str = "a-1000",
    name: str | None = None,
    media_type: str | None = "10/100/1000BaseTX",
) -> dict[str, object]:
    values: dict[str, object] = {
        "status": status,
        "vlan": vlan,
        "duplex_code": duplex,
        "port_speed": speed,
    }
    if name is not None:
        values["name"] = name
    if media_type is not None:
        values["type"] = media_type
    return values


@pytest.mark.parametrize("platform", [PlatformFamily.IOS, PlatformFamily.IOS_XE])
def test_productive_genie_parser_normalizes_valid_fixture_and_preserves_raw(
    platform: PlatformFamily,
) -> None:
    execution = _execution()
    content = FIXTURE.read_text(encoding="utf-8")
    original_bytes = content.encode("utf-8")
    independent_sha256 = hashlib.sha256(original_bytes).hexdigest()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    result = IOSShowInterfacesStatusParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=platform,
    )

    assert result.status is ParseStatus.SUCCESS
    assert result.warnings == ()
    assert isinstance(result.data, InterfaceObservation)
    assert result.data.schema_version == "0.1"
    assert result.data.platform is platform
    assert [record.ordinal for record in result.data.interfaces] == list(range(1, 8))
    assert [record.interface for record in result.data.interfaces] == _EXPECTED_INTERFACES
    assert [record.status for record in result.data.interfaces] == [
        "connected",
        "notconnect",
        "disabled",
        "err-disabled",
        "connected",
        "connected",
        "connected",
    ]

    assert result.data.interfaces[0].description == "USER-ACCESS"
    assert result.data.interfaces[1].description is None
    assert result.data.interfaces[0].vlan == "10"
    assert result.data.interfaces[4].vlan == "trunk"
    assert result.data.interfaces[5].vlan == "routed"
    assert result.data.interfaces[1].duplex == "auto"
    assert result.data.interfaces[4].duplex == "a-full"
    assert result.data.interfaces[1].speed == "auto"
    assert result.data.interfaces[4].speed == "a-1000"
    assert result.data.interfaces[5].speed == "a-10G"
    assert result.data.interfaces[0].media_type == "10/100/1000BaseTX"
    assert result.data.interfaces[4].media_type == "1000BaseLX SFP"
    assert result.data.interfaces[5].media_type == "10GBase-SR"
    assert result.data.interfaces[6].media_type is None

    evidence_by_field = {item.field: item for item in result.evidence}
    assert evidence_by_field["interfaces"].line_start == 2
    assert evidence_by_field["interfaces"].line_end == 8
    for index, expected_line in enumerate(range(2, 9)):
        prefix = f"interfaces[{index}]"
        for field in (prefix, f"{prefix}.ordinal", f"{prefix}.interface", f"{prefix}.status"):
            assert evidence_by_field[field].line_start == expected_line
            assert evidence_by_field[field].line_end == expected_line
    assert evidence_by_field["interfaces[4].vlan"].line_start == 6
    assert evidence_by_field["interfaces[5].media_type"].line_start == 7
    assert "interfaces[1].description" not in evidence_by_field
    assert "interfaces[6].media_type" not in evidence_by_field

    raw_lines = content.splitlines()
    for index, canonical_name in enumerate(_EXPECTED_INTERFACES):
        source = evidence_by_field[f"interfaces[{index}].interface"]
        raw_name = raw_lines[source.line_start - 1].split(maxsplit=1)[0]
        assert _fake_convert(raw_name) == canonical_name

    assert result.trace.parser_id is ParserId.IOS_SHOW_INTERFACES_STATUS_V1
    assert result.trace.parser_version == "0.1.0"
    assert result.trace.command_id is CommandId.INTERFACES_STATUS
    assert result.trace.normalized_model is NormalizedModelId.INTERFACE_OBSERVATION
    assert result.trace.raw_sha256 == independent_sha256
    assert raw.sha256 == independent_sha256
    assert raw.content == content
    assert raw.content.encode(raw.encoding) == original_bytes


def test_genie_boundary_passes_only_precollected_output_and_device_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class FakeShowInterfacesStatus:
        def __init__(self, *, device: object) -> None:
            calls["device"] = device

        def cli(self, *, output: str) -> dict[str, object]:
            calls["output"] = output
            return {
                "interfaces": {
                    "GigabitEthernet1/0/1": _genie_values(name="USER-ACCESS")
                }
            }

    class FakeCommon:
        @staticmethod
        def convert_intf_name(raw_interface: str) -> str:
            return _fake_convert(raw_interface)

    def fake_import(name: str) -> object:
        if name == "genie.libs.parser.iosxe.show_interface":
            return SimpleNamespace(ShowInterfacesStatus=FakeShowInterfacesStatus)
        if name == "genie.libs.parser.utils.common":
            return SimpleNamespace(Common=FakeCommon)
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(parser_module, "import_module", fake_import)
    content = (
        "Port Name Status Vlan Duplex Speed Type\n"
        "Gi1/0/1 USER-ACCESS connected 10 a-full a-1000 10/100/1000BaseTX\n"
    )
    _, _, result = _parse_content(content)

    assert calls == {"device": None, "output": content}
    assert result.status is ParseStatus.SUCCESS


def test_unparsed_raw_candidate_and_count_mismatch_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = IOSShowInterfacesStatusParser()
    genie_interfaces = {
        "GigabitEthernet1/0/1": _genie_values(name="ONE"),
    }
    monkeypatch.setattr(
        parser,
        "_extract_with_genie",
        lambda content, platform: (genie_interfaces, _fake_convert),
    )
    content = (
        "Port Name Status Vlan Duplex Speed Type\n"
        "Gi1/0/1 ONE connected 10 a-full a-1000 10/100/1000BaseTX\n"
        "Gi1/0/2 TWO notconnect 20 auto auto 10/100/1000BaseTX\n"
    )
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    result = parser.parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.PARTIAL
    assert [warning.code for warning in result.warnings] == [
        "genie_unparsed_interface",
        "genie_interface_count_mismatch",
    ]
    assert result.data.interfaces[0].interface == "GigabitEthernet1/0/1"


def test_duplicate_raw_rows_make_genie_source_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = IOSShowInterfacesStatusParser()
    genie_interfaces = {"GigabitEthernet1/0/1": _genie_values(name="ONE")}
    monkeypatch.setattr(
        parser,
        "_extract_with_genie",
        lambda content, platform: (genie_interfaces, _fake_convert),
    )
    content = (
        "Port Name Status Vlan Duplex Speed Type\n"
        "Gi1/0/1 ONE connected 10 a-full a-1000 10/100/1000BaseTX\n"
        "Gi1/0/1 ONE connected 10 a-full a-1000 10/100/1000BaseTX\n"
    )
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    result = parser.parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.PARTIAL
    assert [warning.code for warning in result.warnings] == [
        "duplicate_raw_interface_row",
        "genie_source_line_not_unique",
        "genie_interface_count_mismatch",
    ]
    assert not any(item.field.startswith("interfaces[0]") for item in result.evidence)


def test_genie_interface_without_raw_row_is_retained_but_has_no_false_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = IOSShowInterfacesStatusParser()
    genie_interfaces = {
        "GigabitEthernet1/0/1": _genie_values(name="ONE"),
        "GigabitEthernet1/0/9": _genie_values(name="NINE"),
    }
    monkeypatch.setattr(
        parser,
        "_extract_with_genie",
        lambda content, platform: (genie_interfaces, _fake_convert),
    )
    content = (
        "Port Name Status Vlan Duplex Speed Type\n"
        "Gi1/0/1 ONE connected 10 a-full a-1000 10/100/1000BaseTX\n"
    )
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    result = parser.parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.PARTIAL
    assert [record.interface for record in result.data.interfaces] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/9",
    ]
    assert [warning.code for warning in result.warnings] == [
        "genie_source_line_not_unique",
        "genie_interface_count_mismatch",
    ]
    assert not any(item.field.startswith("interfaces[1]") for item in result.evidence)


def test_genie_import_and_runtime_failures_are_framework_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (
        "Port Name Status Vlan Duplex Speed Type\n"
        "Gi1/0/1 ONE connected 10 a-full a-1000 10/100/1000BaseTX\n"
    )
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    def missing_import(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(parser_module, "import_module", missing_import)
    with pytest.raises(GenieDependencyError) as dependency_error:
        IOSShowInterfacesStatusParser().parse(
            raw_output=raw,
            command_execution=execution,
            platform=PlatformFamily.IOS_XE,
        )
    assert dependency_error.value.command_execution_id == execution.id
    assert dependency_error.value.raw_output_id == raw.id

    class FailingShowInterfacesStatus:
        def __init__(self, *, device: object) -> None:
            assert device is None

        def cli(self, *, output: str) -> dict[str, object]:
            del output
            raise RuntimeError("internal Genie failure")

    class FakeCommon:
        @staticmethod
        def convert_intf_name(raw_interface: str) -> str:
            return _fake_convert(raw_interface)

    def runtime_import(name: str) -> object:
        if name == "genie.libs.parser.iosxe.show_interface":
            return SimpleNamespace(ShowInterfacesStatus=FailingShowInterfacesStatus)
        if name == "genie.libs.parser.utils.common":
            return SimpleNamespace(Common=FakeCommon)
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(parser_module, "import_module", runtime_import)
    with pytest.raises(GenieExtractionError) as extraction_error:
        IOSShowInterfacesStatusParser().parse(
            raw_output=raw,
            command_execution=execution,
            platform=PlatformFamily.IOS_XE,
        )
    assert extraction_error.value.command_execution_id == execution.id
    assert extraction_error.value.raw_output_id == raw.id


def test_productive_registry_resolves_ios_and_iosxe_and_rejects_nxos() -> None:
    registry = build_parser_registry()

    ios = registry.resolve(ParserId.IOS_SHOW_INTERFACES_STATUS_V1, PlatformFamily.IOS)
    iosxe = registry.resolve(ParserId.IOS_SHOW_INTERFACES_STATUS_V1, PlatformFamily.IOS_XE)
    assert isinstance(ios, IOSShowInterfacesStatusParser)
    assert isinstance(iosxe, IOSShowInterfacesStatusParser)

    with pytest.raises(UnsupportedPlatformError):
        registry.resolve(ParserId.IOS_SHOW_INTERFACES_STATUS_V1, PlatformFamily.NX_OS)
