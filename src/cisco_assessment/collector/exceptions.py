"""Collector-specific errors with stable machine-readable error types."""

from __future__ import annotations

from typing import ClassVar


class CollectorError(Exception):
    """Base error for collection infrastructure."""

    error_type: ClassVar[str] = "collector_error"


class TransportError(CollectorError):
    """Base error for SSH transport failures."""

    error_type = "transport_error"


class ConnectionTimeoutError(TransportError):
    error_type = "connection_timeout"


class AuthenticationError(TransportError):
    error_type = "authentication_failed"


class ConnectionLostError(TransportError):
    error_type = "connection_lost"


class SessionError(CollectorError):
    """Base error for interactive CLI session failures."""

    error_type = "session_error"


class SessionSetupError(SessionError):
    error_type = "session_setup_failed"


class UnsupportedCollectorPlatformError(SessionError):
    error_type = "unsupported_collector_platform"


class CommandError(CollectorError):
    """Base command error that can carry evidence received before failure."""

    error_type = "command_error"

    def __init__(self, message: str, *, partial_raw: bytes = b"") -> None:
        super().__init__(message)
        self.partial_raw = partial_raw


class CommandTimeoutError(CommandError):
    error_type = "command_timeout"


class CommandCliError(CommandError):
    """Device CLI rejected or failed a query command."""

    error_type = "cli_error"

    def __init__(self, message: str, *, cli_error_type: str, partial_raw: bytes) -> None:
        super().__init__(message, partial_raw=partial_raw)
        self.cli_error_type = cli_error_type


class CommandPolicyError(CollectorError):
    error_type = "read_only_policy_rejected"


class RawPersistenceError(CollectorError):
    error_type = "raw_persistence_failed"
