"""Public API for deterministic normalized-data assessment."""

from .catalog import DuplicateRuleError, RuleCatalog
from .context import AssessmentContext
from .device_info_rules import (
    DEVICE_INFO_RULES,
    IOSXEBootModeRule,
    NonDefaultHostnameRule,
    SoftwareVersionObservedRule,
    device_info_rule_catalog,
)
from .engine import AssessmentEngine
from .enums import AssessmentStatus, FindingSeverity, RuleCategory
from .evidence import EvidenceRequest, FindingEvidence, NormalizedFieldSource, SourceTrace
from .hardware_inventory_rules import (
    HARDWARE_INVENTORY_RULES,
    ChassisIdentityObservedRule,
    HardwareInventoryObservedRule,
    UniqueInventorySerialsRule,
    hardware_inventory_rule_catalog,
)
from .models import AssessmentResult, Finding, RuleDecision, RuleMetadata, RuleOutcome
from .rules import AssessmentRule

__all__ = [
    "DEVICE_INFO_RULES",
    "HARDWARE_INVENTORY_RULES",
    "AssessmentContext",
    "AssessmentEngine",
    "AssessmentResult",
    "AssessmentRule",
    "AssessmentStatus",
    "ChassisIdentityObservedRule",
    "DuplicateRuleError",
    "EvidenceRequest",
    "Finding",
    "FindingEvidence",
    "FindingSeverity",
    "HardwareInventoryObservedRule",
    "IOSXEBootModeRule",
    "NonDefaultHostnameRule",
    "NormalizedFieldSource",
    "RuleCatalog",
    "RuleCategory",
    "RuleDecision",
    "RuleMetadata",
    "RuleOutcome",
    "SoftwareVersionObservedRule",
    "SourceTrace",
    "UniqueInventorySerialsRule",
    "device_info_rule_catalog",
    "hardware_inventory_rule_catalog",
]
