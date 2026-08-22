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

## Characterization fixture and observed Genie result

The sanitized fixture contains seven rows covering access, disconnected, administratively disabled, err-disabled, trunk, routed, optical media, auto negotiation, 10G, and a Port-channel without a media type.

The characterization test executed the real Genie 26.6 parser with `ShowInterfacesStatus(device=None).cli(output=content)` and observed exactly:

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

All seven fixture ports are returned exactly once.

## RAW -> Genie -> framework mapping

| RAW column/value | Genie | Framework field | Transformation |
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

For the valid seven-row fixture, status evidence resolves to RAW lines `2, 3, 4, 5, 6, 7, 8`, `ParseStatus.SUCCESS` is produced, and warnings are empty. The test also computes SHA-256 independently before parsing and verifies that `RawCommandOutput.content`, bytes, SHA-256, and `ParseResult.trace.raw_sha256` remain unchanged.

## Dependency closure and footprint

The first experiment attempted to construct a minimal runtime with `--no-deps`. That approach was rejected for productization evaluation because imports progressively exposed undeclared/indirect runtime requirements.

The reproducible spike now installs only two top-level requirements and lets pip resolve their complete dependency closure normally:

```text
genie==26.6
pyats==26.6
```

`genie==26.6` alone resolves successfully according to its package metadata and passes `pip check`, but importing `genie.metaparser` then fails because the runtime imports `pyats`, which is not declared by the `genie` distribution. Adding the top-level `pyats==26.6` package is therefore required. The `pyats` meta-package resolves its own component family, including `pyats.reporter`, `pyats.topology`, and `pyats.connections`. Our code does not create a Testbed or connection; those packages are dependency footprint only.

With `genie==26.6` plus `pyats==26.6` on Python 3.11/Ubuntu, the resolver produced a healthy environment:

- `pip check`: **No broken requirements found**.
- exact imports for `ShowInterfacesStatus` and `Common`: **success**.
- new or changed `pip freeze` entries relative to the project test environment: **83**.
- `site-packages` before: **145,692 KiB**.
- `site-packages` after: **875,652 KiB**.
- observed delta: **729,960 KiB (~713 MiB / ~0.70 GiB)**.

The resolver-selected Cisco package families were:

```text
genie==26.6
genie.libs.clean==26.6
genie.libs.conf==26.6
genie.libs.filetransferutils==26.6
genie.libs.health==26.6
genie.libs.ops==26.6
genie.libs.parser==26.6
genie.libs.sdk==26.6
pyats==26.6
pyats.aereport==26.6
pyats.aetest==26.6
pyats.async==26.6
pyats.connections==26.6
pyats.datastructures==26.6
pyats.easypy==26.6
pyats.kleenex==26.6
pyats.log==26.6
pyats.reporter==26.6
pyats.results==26.6
pyats.tcl==26.6
pyats.topology==26.6
pyats.utils==26.6
unicon==26.6
unicon.plugins==26.6
rest.connector==26.6
yang.connector==26.6
```

Other resolver-selected additions include `aiohttp`, `asyncssh`, `ciscoisesdk`, `dill`, `gitpython`, `grpcio`, `jinja2`, `lxml`, `ncclient`, `netaddr`, `protobuf`, `psutil`, `pyVmomi`, `pyftpdlib`, `pysnmp`, `requests`, `ruamel.yaml`, `tftpy`, `xmltodict`, and their transitive dependencies. The workflow records the complete sorted `pip freeze` so the observed footprint is reproducible and auditable.

This footprint is intentionally accepted for the spike. Dependency reduction or packaging isolation is a separate optimization problem and is not required to demonstrate the parser integration.

## Validation results

With the normally resolved Genie/pyATS environment, the spike tests demonstrate:

- Genie receives only a pre-collected string through `cli(output=content)`;
- parser instance uses `device=None`; no device connection exists;
- all seven fixture records are extracted exactly once;
- `Gi1/0/1` is deterministically expanded to `GigabitEthernet1/0/1`;
- `connected`, `notconnect`, `disabled`, and `err-disabled` are preserved;
- numeric VLAN, `trunk`, and `routed` are preserved as strings;
- `auto`, `a-full`, `a-1000`, and `a-10G` are preserved;
- optical media is retained and media can be absent on a Port-channel;
- the framework adapter produces `InterfaceObservation`;
- every normalized field with source data receives framework-owned `FieldEvidence` pointing to the correct RAW line;
- RAW bytes and SHA-256 remain immutable;
- parser status is `SUCCESS`;
- the valid fixture produces zero warnings.

The normal framework test suite also remains independent from the spike dependency installation.

## Known limitations before productization

- Genie canonicalizes the interface key, so exact RAW spelling must be retained through separate evidence rather than inferred from the normalized key.
- `name` is optional and disappears for an empty description.
- `type` is optional and is absent on rows such as Port-channel entries.
- VLAN is always a string and can represent a numeric VLAN, `trunk`, `routed`, or another non-space token.
- The parser has a closed status-token regex. A valid IOS/IOS-XE status outside that set causes the whole row not to match.
- Genie does not provide RAW line numbers, columns, or substrings, so framework traceability must remain outside Genie.
- The normally resolved runtime has a large footprint (~713 MiB observed delta) and includes pyATS connection/topology components even though this integration does not use them.
- The spike does not introduce a generic `ParserBackend`; the integration remains specific to `IOSShowInterfacesStatusParser`.

## Productization proposal

`IOSShowInterfacesStatusParser` can remain a normal `BaseParser[InterfaceObservation]`. `_parse_content()` should call Genie with `output=content`, adapt the returned dictionary into the framework-owned immutable Pydantic model, independently construct `FieldEvidence` from the RAW line index, and return `ParsedPayload`.

Productization should preserve these boundaries:

- do not give Genie a device or Testbed;
- do not let Genie execute commands;
- retain `RawCommandOutput` as the immutable source of truth;
- keep the adapter and normalized model framework-owned;
- keep provenance/line mapping framework-owned;
- do not introduce a generic parser-backend abstraction until another concrete integration demonstrates the need;
- treat the dependency footprint as a packaging/isolation follow-up rather than changing the parsing architecture.

The parser should only be added to the productive registry after this spike is accepted and the InterfaceObservation contract is finalized.
