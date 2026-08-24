"""Stable enums for PR Review Agent v0.1."""

from enum import StrEnum


class ReviewDecision(StrEnum):
    """Final deterministic recommendation emitted by the review agent."""

    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    BLOCKED = "BLOCKED"


class ReviewCheckStatus(StrEnum):
    """Outcome of evaluating one review check."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class ReviewFindingSeverity(StrEnum):
    """Impact of one review finding."""

    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


class ReviewEvidenceKind(StrEnum):
    """Stable kinds of evidence supporting review checks and findings."""

    PR_METADATA = "PR_METADATA"
    DIFF = "DIFF"
    FILE = "FILE"
    SOURCE_LINE = "SOURCE_LINE"
    TEST = "TEST"
    TEST_OUTPUT = "TEST_OUTPUT"
    CI_CHECK = "CI_CHECK"
    COMMIT = "COMMIT"
    FIXTURE = "FIXTURE"
    HASH = "HASH"
    CONFIG = "CONFIG"
    ISSUE = "ISSUE"
    HANDOFF = "HANDOFF"
    COMMAND_RESULT = "COMMAND_RESULT"


class ComponentId(StrEnum):
    """Repository components used for scope classification."""

    ARCHITECTURE = "ARCHITECTURE"
    COLLECTOR = "COLLECTOR"
    COMMAND_CATALOG = "COMMAND_CATALOG"
    RAW_MODELS = "RAW_MODELS"
    NORMALIZED_MODELS = "NORMALIZED_MODELS"
    PARSER = "PARSER"
    ENGINE = "ENGINE"
    RULES = "RULES"
    TESTING_FIXTURES = "TESTING_FIXTURES"
    REPORTING = "REPORTING"
    ASSESSMENT_PLAN = "ASSESSMENT_PLAN"
    RUNNER_CLI = "RUNNER_CLI"
    CI_TOOLING = "CI_TOOLING"
    DOCUMENTATION = "DOCUMENTATION"
    UNKNOWN = "UNKNOWN"
