Apply these source-level changes to the supplied file:

1. Change the class docstring suffix from `HardwareInventory v0.2` to `HardwareInventory v0.3` and change `_descriptor.parser_version` from `"0.2.0"` to `"0.3.0"`.

2. Add these compiled expressions beside the existing record-identity expressions:

_SLOT_OWNER_RE = re.compile(
    r"^(?P<role>Supervisor|Linecard)\s*\(slot\s+(?P<slot>\d+)\)$",
    re.IGNORECASE,
)
_MODULAR_INTERFACE_RE = re.compile(
    r"^(?:Gi|Te|Tw|Fo|Hu|Eth|Ethernet|GigabitEthernet|TenGigabitEthernet|"
    r"TwentyFiveGigE|FortyGigabitEthernet|HundredGigE)"
    r"(?P<slot>\d+)/\d+$",
    re.IGNORECASE,
)
_ANY_INTERFACE_RE = re.compile(
    r"^(?:Gi|Te|Tw|Fo|Hu|Eth|Ethernet|GigabitEthernet|TenGigabitEthernet|"
    r"TwentyFiveGigE|FortyGigabitEthernet|HundredGigE)"
    r"(?:\d+/\d+|\d+/\d+/\d+)$",
    re.IGNORECASE,
)
_OPTIC_DESCRIPTION_RE = re.compile(
    r"(?:transceiver|(?:10|100|1000|10g|25g|40g|100g)base[a-z0-9-]*|"
    r"\b(?:sfp|qsfp|x2|xfp)\b)",
    re.IGNORECASE,
)

3. After constructing `member_ids`, construct a unique modular-slot owner map and pass it into parent resolution:

        slot_owner_ids = self._build_unique_slot_owner_id_map(observed)
        records = tuple(
            _Record(
                record=HardwareInventoryRecord(
                    ordinal=item.ordinal,
                    name=item.name,
                    description=item.description,
                    pid=item.pid,
                    vid=item.vid,
                    serial_number=item.serial_number,
                    component_type=item.component_type,
                    parent_id=self._resolve_parent_id(
                        item,
                        member_ids,
                        slot_owner_ids,
                    ),
                ),
                start_line=item.start_line,
                end_line=item.end_line,
            )
            for item in observed
        )

4. Add this method immediately after `_build_unique_member_id_map`:

    @staticmethod
    def _build_unique_slot_owner_id_map(
        records: list[_ObservedRecord],
    ) -> dict[int, str]:
        candidates: dict[int, list[str]] = {}
        owner_types = {
            HardwareComponentType.SUPERVISOR,
            HardwareComponentType.LINE_CARD,
        }
        for item in records:
            if item.component_type not in owner_types:
                continue
            match = _SLOT_OWNER_RE.fullmatch(item.name)
            if match is None:
                continue
            slot = int(match.group("slot"))
            candidates.setdefault(slot, []).append(
                hardware_inventory_record_id(item.ordinal)
            )

        return {
            slot: ids[0]
            for slot, ids in candidates.items()
            if len(ids) == 1
        }

5. Replace `_resolve_parent_id` with:

    @classmethod
    def _resolve_parent_id(
        cls,
        record: _ObservedRecord,
        member_ids: dict[int, str],
        slot_owner_ids: dict[int, str],
    ) -> str | None:
        if record.component_type is HardwareComponentType.CHASSIS_MEMBER:
            return None

        member = cls._explicit_parent_member(record)
        if member is not None:
            return member_ids.get(member)

        if record.component_type is not HardwareComponentType.TRANSCEIVER:
            return None
        interface_match = _MODULAR_INTERFACE_RE.fullmatch(record.name)
        if interface_match is None:
            return None
        return slot_owner_ids.get(int(interface_match.group("slot")))

6. Replace `_classify` with the following precedence-preserving implementation:

    @staticmethod
    def _classify(
        *,
        name: str,
        description: str | None,
        pid: str | None,
    ) -> HardwareComponentType:
        name_folded = name.casefold()
        description_folded = (description or "").casefold()
        pid_upper = (pid or "").upper()
        combined = f"{name_folded} {description_folded}"
        slot_owner = _SLOT_OWNER_RE.fullmatch(name)

        if (
            _SWITCH_MEMBER_RE.fullmatch(name) is not None
            or name_folded == "chassis"
            or name_folded == "switch system"
            or "switch system" in description_folded
        ):
            return HardwareComponentType.CHASSIS_MEMBER
        if slot_owner is not None:
            if slot_owner.group("role").casefold() == "supervisor":
                return HardwareComponentType.SUPERVISOR
            return HardwareComponentType.LINE_CARD
        if _STACK_PORT_RE.fullmatch(name) is not None:
            return HardwareComponentType.STACK_CABLE_ENDPOINT
        if "power supply" in combined or pid_upper.startswith("PWR-"):
            return HardwareComponentType.POWER_SUPPLY
        if "fan" in combined or pid_upper.endswith("-FAN"):
            return HardwareComponentType.FAN

        interface_record = _ANY_INTERFACE_RE.fullmatch(name) is not None
        optic_pid = pid_upper.startswith(
            ("GLC-", "SFP-", "QSFP-", "X2-", "XFP-")
        )
        optic_description = (
            _OPTIC_DESCRIPTION_RE.search(description or "") is not None
        )
        if interface_record and (optic_pid or optic_description):
            return HardwareComponentType.TRANSCEIVER

        if (
            "stack adapter" in combined
            or "stackadapter" in combined
            or "STACK-ADPT" in pid_upper
            or "STACK-ADAPTER" in pid_upper
        ):
            return HardwareComponentType.STACK_ADAPTER
        if (
            "network module" in combined
            or "uplink module" in combined
            or _NETWORK_MODULE_PID_RE.search(pid_upper) is not None
        ):
            return HardwareComponentType.NETWORK_MODULE
        return HardwareComponentType.OTHER

All other supplied source content remains byte-for-byte unchanged.