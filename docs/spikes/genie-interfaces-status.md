# Genie `show interfaces status` spike

## Scope

This spike evaluates Cisco Genie only as an extraction engine over an already-collected in-memory RAW string. It does not give Genie a device connection and does not alter `CiscoIOSSession`, `CommandExecution`, `RawCommandOutput`, `ParserRegistry`, Runner, CLI, Reporting, HardwareInventory, AssessmentPlan, or Assessment Rules.

Target boundary:

`Collector -> RawCommandOutput -> BaseParser -> Genie extraction -> framework adapter -> InterfaceObservation -> FieldEvidence`

## Genie API verified from current parser source

`genie.libs.parser.iosxe.show_interface.ShowInterfacesStatus.cli(interface="", output=None)` accepts an `output` argument. `device.execute()` is called only when `output is None`. The spike therefore instantiates the parser with `device=None` and calls `cli(output=content)`.

The IOS-XE schema is:

```python
{
    "interfaces": {
        <canonical interface>: {
            # optional
            "name": str,
            "status": str,
            "vlan": str,
            "duplex_code": str,
            "port_speed": str,
            # optional
            "type": str,
        }
    }
}
```

The parser accepts these status tokens in its row regex: `connected`, `notconnect`, `suspended`, `inactive`, `disabled`, `err-disabled`, and `monitoring`.

## Characterization fixture

The sanitized fixture contains seven rows covering access, disconnected, administratively disabled, err-disabled, trunk, routed, optical media, auto negotiation, 10G, and a Port-channel without a media type.

Expected Genie result for the fixture:

```python
{
    "interfaces": {
        "GigabitEthernet1/0/1": {
            "name": "USER-ACCESS",
            "status": "connected",
            "vlan": "10",
            "duplex_code": "a-full",
            "port_speed": "a-1000",
            "type": "10/100/1000BaseTX",
        },
        "GigabitEthernet1/0/2": {
            "status": "notconnect",
            "vlan": "20",
            "duplex_code": "auto",
            "port_speed": "auto",
            "type": "10/100/1000BaseTX",
        },
        "GigabitEthernet1/0/3": {
            "name": "ADMIN-DOWN",
            "status": "disabled",
            "vlan": "30",
            "duplex_code": "auto",
            "port_speed": "auto",
            "type": "10/100/1000BaseTX",
        },
        "GigabitEthernet1/0/4": {
            "name": "BPDU-GUARD",
            "status": "err-disabled",
            "vlan": "40",
            "duplex_code": "auto",
            "port_speed": "auto",
            "type": "10/100/1000BaseTX",
        },
        "GigabitEthernet1/0/47": {
            "name": "CORE-TRUNK",
            "status": "connected",
            "vlan": "trunk",
            "duplex_code": "a-full",
            "port_speed": "a-1000",
            "type": "1000BaseLX SFP",
        },
        "TenGigabitEthernet1/1/1": {
            "name": "DIST-UPLINK",
            "status": "connected",
            "vlan": "routed",
            "duplex_code": "full",
            "port_speed": "a-10G",
            "type": "10GBase-SR",
        },
        "Port-channel10": {
            "name": "SERVER-LAG",
            "status": "connected",
            "vlan": "trunk",
            "duplex_code": "a-full",
            "port_speed": "a-10G",
        },
    }
}
```

## RAW -> Genie -> framework mapping

| RAW column/value | Genie | Proposed framework field | Transformation |
| --- | --- | --- | --- |
| `Gi1/0/1` | dict key `GigabitEthernet1/0/1` | `interfaces[n].interface` | Genie expands interface abbreviation |
| `USER-ACCESS` | `name` | `interfaces[n].description` | whitespace trimmed; omitted if blank |
| `connected` | `status` | `interfaces[n].status` | preserved string |
| `10` | `vlan` | `interfaces[n].vlan` | preserved string, not converted to integer |
| `trunk` | `vlan` | `interfaces[n].vlan` | preserved string |
| `routed` | `vlan` | `interfaces[n].vlan` | preserved string |
| `auto`, `a-full`, `full` | `duplex_code` | `interfaces[n].duplex` | preserved string |
| `auto`, `a-1000`, `a-10G` | `port_speed` | `interfaces[n].speed` | preserved string |
| `10GBase-SR`, `1000BaseLX SFP` | `type` | `interfaces[n].media_type` | rest of line, trimmed; optional |

No semantic conversion of VLAN, duplex, speed, or media is performed by this Genie parser.

## Traceability strategy

Genie returns values but no line numbers or source spans. The adapter therefore builds a separate, deterministic RAW line index without modifying the RAW text:

1. enumerate the original `content.splitlines()` with one-based line numbers;
2. identify only rows containing a status token supported by the Genie parser;
3. take only the first token as the RAW interface identifier;
4. canonicalize that token with the same `Common.convert_intf_name()` utility Genie uses;
5. require a unique RAW row for each Genie interface key;
6. attach every normalized field derived from that row to the same `FieldEvidence.line_start/line_end`;
7. emit warnings when a RAW candidate is absent from Genie, Genie has no source row, duplicate candidate rows exist, or counts differ.

This locator is intentionally not a second semantic interface parser: status/VLAN/duplex/speed/type continue to come only from Genie.

## Dependency isolation

The normal project dependencies are unchanged. The spike keeps its dependency list under `requirements/spikes/genie-interfaces-status.txt` and its own workflow.

The top-level `genie` distribution is installed with `--no-deps` because its declared dependency set pulls unrelated Genie libraries such as clean/conf/ops/sdk. The same is done for `genie.libs.parser`. Only imports exercised by this parser path are then installed explicitly: targeted pyATS logging/configuration/utils components, `xmltodict`, and `packaging`.

The CI result is the acceptance test for whether this reduced set is actually sufficient; any missing import must be added only after it is observed.

## Known limitations to evaluate before productization

- Genie canonicalizes the interface key, so exact RAW spelling must be retained through separate evidence rather than inferred from the normalized key.
- `name` is optional and disappears for an empty description.
- `type` is optional and is absent on rows such as Port-channel entries.
- VLAN is always a string and can represent a numeric VLAN, `trunk`, `routed`, or another non-space token.
- The parser has a closed status-token regex. A valid IOS/IOS-XE status outside that set causes the whole row not to match.
- Genie does not provide RAW line numbers, columns, or substrings, so framework traceability must remain outside Genie.
- The spike does not introduce a generic `ParserBackend`; the integration is specific to `IOSShowInterfacesStatusParser`.

## Productization proposal

If the characterization tests pass, `IOSShowInterfacesStatusParser` can remain a normal `BaseParser[InterfaceObservation]`. `_parse_content()` should call Genie with `output=content`, adapt the returned dictionary into the framework-owned immutable Pydantic model, independently construct `FieldEvidence` from the RAW line index, and return `ParsedPayload`. The parser should only be added to the productive registry after the dependency/fixture behavior is accepted and the interface model contract is finalized.
