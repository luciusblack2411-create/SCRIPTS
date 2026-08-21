class CollectorError(Exception):
    error_code = "COLLECTOR_ERROR"

class TransportError(CollectorError):
    error_code = "TRANSPORT_ERROR"

class ConnectionTimeoutError(TransportError):
    error_code = "CONNECTION_TIMEOUT"

class AuthenticationError(TransportError):
    error_code = "AUTHENTICATION_FAILED"

class ConnectionLostError(TransportError):
    error_code = "CONNECTION_LOST"

class SessionError(CollectorError):
    error_code = "SESSION_ERROR"

class SessionSetupError(SessionError):
    error_code = "SESSION_SETUP_FAILED"

class CommandError(CollectorError):
    def __init__(self, message: str, *, partial_raw: bytes = b"") -> None:
        super().__init__(message)
        self.partial_raw = partial_raw

class CommandTimeoutError(CommandError):
    error_code = "COMMAND_TIMEOUT"

class CommandUnsupportedError(CommandError):
    error_code = "COMMAND_UNSUPPORTED"

class CommandAuthorizationError(CommandError):
    error_code = "COMMAND_AUTHORIZATION_FAILED"

class CommandPolicyError(CommandError):
    error_code = "COMMAND_POLICY_REJECTED"

class RawPersistenceError(CollectorError):
    error_code = "RAW_WRITE_FAILED"
