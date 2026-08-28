from __future__ import annotations

from hashlib import sha256
from pathlib import Path

FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "ios"
    / "show_inventory"
    / "c4506e_ios_real_sanitized.raw"
)

EXPECTED_SHA256 = (
    "a7f02f982177caaa361d9dfe84265d18d699c17e3833ca2fe1c077d3541f6b27"
)

EXPECTED_RECORD_NAMES = (
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
)


def test_c4506e_real_sanitized_raw_is_byte_locked() -> None:
    raw = FIXTURE.read_bytes()

    assert len(raw) == 1709
    assert raw.count(b"\n") == 41
    assert sha256(raw).hexdigest() == EXPECTED_SHA256


def test_c4506e_real_sanitized_raw_preserves_record_order() -> None:
    raw = FIXTURE.read_bytes()
    text = raw.decode("utf-8")

    assert raw.startswith(b"show inventory\r\n")

    observed_names = tuple(
        line.split('"', 2)[1]
        for line in text.splitlines()
        if line.startswith('NAME: "')
    )

    assert observed_names == EXPECTED_RECORD_NAMES
    assert len(observed_names) == 13


def test_c4506e_real_fixture_preserves_parser_relevant_physical_identity() -> None:
    text = FIXTURE.read_text(encoding="utf-8")

    assert (
        'NAME: "Supervisor(slot 1)", '
        'DESCR: "Supervisor 6L-E 10GE (X2), 1000BaseX (SFP) '
        'with 2 10GE X2 ports"'
    ) in text

    assert 'NAME: "Linecard(slot 4)", DESCR: "1000BaseX (GBIC) with 6 1000 GBIC ports"' in text

    for port in range(1, 6):
        assert (
            f'NAME: "GigabitEthernet4/{port}", DESCR: "1000BaseSX"'
            in text
        )

    assert 'NAME: "FanTray 1", DESCR: "FanTray"' in text
    assert (
        'NAME: "Power Supply 1", DESCR: "Power Supply ( AC 2800W )"'
        in text
    )
    assert (
        'NAME: "Power Supply 2", DESCR: "Power Supply ( AC 2800W )"'
        in text
    )
