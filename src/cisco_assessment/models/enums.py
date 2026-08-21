"""Enums shared across MVP data models."""

from enum import StrEnum


class PlatformFamily(StrEnum):
    IOS = "ios"
    IOS_XE = "ios_xe"
    NX_OS = "nx_os"
    UNKNOWN = "unknown"


class AssessmentRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class CommandExecutionStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    TIMEOUT = "timeout"
    CLI_ERROR = "cli_error"
    TRANSPORT_ERROR = "transport_error"
    SKIPPED = "skipped"
