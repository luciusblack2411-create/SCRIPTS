"""Initial deterministic Assessment Rules v0.1 for DeviceInfo."""

from __future__ import annotations

from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import DeviceInfo

from .catalog import RuleCatalog
from .context import AssessmentContext
from .enums import AssessmentStatus, FindingSeverity, RuleCategory
from .evidence import EvidenceRequest
from .models import RuleDecision, RuleMetadata

_IOS_PLATFORMS = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})


class NonDefaultHostnameRule:
    """Flag well-known Cisco default hostnames."""

    _metadata = RuleMetadata(
        rule_id="SYS-001",
        version="0.1.0",
        title="Non-default device hostname",
        description="Checks that the device does not use a well-known default Cisco hostname.",
        category=RuleCategory.SYSTEM,
        severity=FindingSeverity.LOW,
        normalized_model="DeviceInfo",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("hostname",),
        evidence_fields=("hostname",),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Configure a unique hostname that follows the organization's device naming standard."
        ),
    )
    _default_hostnames = frozenset({"router", "switch"})

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: DeviceInfo, context: AssessmentContext) -> RuleDecision:
        del context
        assert model.hostname is not None
        hostname = model.hostname
        is_default = hostname.casefold() in self._default_hostnames
        return RuleDecision(
            status=AssessmentStatus.FAIL if is_default else AssessmentStatus.PASS,
            message=(
                f"Device hostname '{hostname}' is a well-known default hostname."
                if is_default
                else f"Device hostname '{hostname}' is not a well-known default hostname."
            ),
            evidence=(EvidenceRequest(field_path="hostname", observed_value=hostname),),
        )


class IOSXEBootModeRule:
    """Surface IOS-XE bundle boot mode for operational review."""

    _metadata = RuleMetadata(
        rule_id="SYS-002",
        version="0.1.0",
        title="IOS-XE boot mode",
        description="Checks whether an IOS-XE switch is operating in INSTALL or BUNDLE boot mode.",
        category=RuleCategory.SYSTEM,
        severity=FindingSeverity.LOW,
        normalized_model="DeviceInfo",
        supported_platforms=frozenset({PlatformFamily.IOS_XE}),
        required_fields=("boot_mode",),
        evidence_fields=("boot_mode",),
        missing_data_status=AssessmentStatus.NOT_APPLICABLE,
        recommendation=(
            "Review BUNDLE mode against the platform's supported operating procedure and prefer "
            "INSTALL mode when required by the organization's standard."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: DeviceInfo, context: AssessmentContext) -> RuleDecision:
        del context
        assert model.boot_mode is not None
        boot_mode = model.boot_mode.upper()
        if boot_mode == "INSTALL":
            status = AssessmentStatus.PASS
            message = "IOS-XE boot mode is INSTALL."
        elif boot_mode == "BUNDLE":
            status = AssessmentStatus.WARNING
            message = "IOS-XE boot mode is BUNDLE and should be reviewed."
        else:
            status = AssessmentStatus.INFO
            message = f"IOS-XE boot mode '{model.boot_mode}' is not classified by this rule."
        return RuleDecision(
            status=status,
            message=message,
            evidence=(EvidenceRequest(field_path="boot_mode", observed_value=model.boot_mode),),
        )


class SoftwareVersionObservedRule:
    """Record the normalized software release as an informational assessment result."""

    _metadata = RuleMetadata(
        rule_id="SYS-003",
        version="0.1.0",
        title="Software version observed",
        description="Records the normalized software release for downstream lifecycle review.",
        category=RuleCategory.SYSTEM,
        severity=FindingSeverity.INFO,
        normalized_model="DeviceInfo",
        supported_platforms=_IOS_PLATFORMS,
        required_fields=("software_version",),
        evidence_fields=("software_version", "system_image"),
        missing_data_status=AssessmentStatus.ERROR,
        recommendation=(
            "Compare the observed software release with the organization's approved lifecycle and "
            "vulnerability policy."
        ),
    )

    @property
    def metadata(self) -> RuleMetadata:
        return self._metadata

    def evaluate(self, model: DeviceInfo, context: AssessmentContext) -> RuleDecision:
        del context
        evidence = [
            EvidenceRequest(
                field_path="software_version",
                observed_value=model.software_version,
            )
        ]
        if model.system_image is not None:
            evidence.append(
                EvidenceRequest(field_path="system_image", observed_value=model.system_image)
            )
        return RuleDecision(
            status=AssessmentStatus.INFO,
            message=f"Device software version is '{model.software_version}'.",
            evidence=tuple(evidence),
        )


DEVICE_INFO_RULES = (
    NonDefaultHostnameRule(),
    IOSXEBootModeRule(),
    SoftwareVersionObservedRule(),
)


def device_info_rule_catalog() -> RuleCatalog[DeviceInfo]:
    """Return the immutable v0.1 rule catalog for DeviceInfo."""

    return RuleCatalog[DeviceInfo](DEVICE_INFO_RULES)
