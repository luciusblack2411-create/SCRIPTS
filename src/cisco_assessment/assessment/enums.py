"""Assessment status and severity enums."""

from enum import StrEnum


class AssessmentStatus(StrEnum):
    """Deterministic result of evaluating one assessment rule."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    INFO = "INFO"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


class FindingSeverity(StrEnum):
    """Impact assigned by rule metadata, independent from evaluation status."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"
