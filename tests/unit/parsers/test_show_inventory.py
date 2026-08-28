Apply these test-source changes to the supplied file:

1. In `test_parse_show_inventory_produces_canonical_v0_3_records`, change:

    assert result.trace.parser_version == "0.2.0"

to:

    assert result.trace.parser_version == "0.3.0"

2. Add this constant near `FIXTURES`:

C4506E_EXPECTED_SHA256 = (
    "a7f02f982177caaa361d9dfe84265d18d699c17e3833ca2fe1c077d3541f6b27"
)

3. Add `from hashlib import sha256` to the imports.

4. Append these tests:

def test_c4506e_physical_identity_and_unique_slot_parent_resolution() -> None:
    execution = _execution()
    fixture = FIXTURES / "c4506e_ios_real_sanitized.raw"
    fixture_bytes = fixture.read_bytes()
    assert sha256(fixture_bytes).hexdigest() == C4506E_EXPECTED_SHA256
    content = fixture_bytes.decode("utf-8")
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content=content,
    )

    result = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS,
    )

    records = result.data.records
    assert result.trace.parser_version == "0.3.0"
    assert result.trace.raw_output_id == raw.id
    assert result.trace.raw_sha256 == raw.sha256
    assert len(records) == 13
    assert [record.ordinal for record in records] == list(range(1, 14))
    assert [record.id for record in records] == [
        f"hw:{ordinal:04d}" for ordinal in range(1, 14)
    ]
    assert [record.name for record in records] == [
        "Switch System",
        "Supervisor(slot 1)",
        "Linecard(slot 2)",
        "Linecard(slot 3)",
        "Linecard(slot 4)",
        "GigabitEthernet4/1",
        "GigabitEthernet4/2",
        "GigabitEthernet4/3",
        "GigabitEthernet4/4",
        "GigabitEthernet4/5",
        "FanTray 1",
        "Power Supply 1",
        "Power Supply 2",
    ]
    assert [record.component_type for record in records] == [
        HardwareComponentType.CHASSIS_MEMBER,
        HardwareComponentType.SUPERVISOR,
        HardwareComponentType.LINE_CARD,
        HardwareComponentType.LINE_CARD,
        HardwareComponentType.LINE_CARD,
        HardwareComponentType.TRANSCEIVER,
        HardwareComponentType.TRANSCEIVER,
        HardwareComponentType.TRANSCEIVER,
        HardwareComponentType.TRANSCEIVER,
        HardwareComponentType.TRANSCEIVER,
        HardwareComponentType.FAN,
        HardwareComponentType.POWER_SUPPLY,
        HardwareComponentType.POWER_SUPPLY,
    ]
    assert all(record.parent_id == "hw:0005" for record in records[5:10])
    assert all(record.parent_id is None for record in records[:5])
    assert all(record.parent_id is None for record in records[10:])
    assert raw.content == content

    raw_lines = content.replace("\r\n", "\n").split("\n")
    for index, record in enumerate(records):
        name_line = next(
            line_number
            for line_number, line in enumerate(raw_lines, start=1)
            if line.startswith(f'NAME: "{record.name}"')
        )
        name_evidence = next(
            item
            for item in result.evidence
            if item.field == f"records[{index}].name"
        )
        assert name_evidence.line_start == name_line
        assert name_evidence.line_end == name_line


def test_modular_slot_parent_requires_one_owner_and_positive_transceiver() -> None:
    execution = _execution()
    content = (
        'NAME: "Linecard(slot 4)", DESCR: "1000BaseX line card"\n'
        "PID: WS-X4448-GB-SFP, VID: V01, SN: LC0001\n"
        'NAME: "Supervisor(slot 4)", DESCR: "Supervisor with SFP ports"\n'
        "PID: WS-X45-SUP, VID: V01, SN: SUP0001\n"
        'NAME: "GigabitEthernet4/1", DESCR: "1000BaseSX"\n'
        "PID: GLC-SX-MM, VID: V01, SN: OPTIC0001\n"
        'NAME: "GigabitEthernet4/2", DESCR: "Copper interface"\n'
        "PID: UNKNOWN, VID: V01, SN: PORT0002\n"
        'NAME: "Linecard(slot 5)", DESCR: "Ethernet line card"\n'
        "PID: WS-X4548, VID: V01, SN: LC0002\n"
        'NAME: "GigabitEthernet5/1", DESCR: "1000BaseSX"\n'
        "PID: GLC-SX-MM, VID: V01, SN: OPTIC0002"
    )
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content=content,
    )

    result = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS,
    )

    records = result.data.records
    assert records[0].component_type is HardwareComponentType.LINE_CARD
    assert records[1].component_type is HardwareComponentType.SUPERVISOR
    assert records[2].component_type is HardwareComponentType.TRANSCEIVER
    assert records[2].parent_id is None
    assert records[3].component_type is HardwareComponentType.OTHER
    assert records[3].parent_id is None
    assert records[5].component_type is HardwareComponentType.TRANSCEIVER
    assert records[5].parent_id == "hw:0005"

All other supplied test content remains unchanged.