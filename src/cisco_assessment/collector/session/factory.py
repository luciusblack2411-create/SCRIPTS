"""Platform-to-session factory."""

from __future__ import annotations

from cisco_assessment.collector.exceptions import UnsupportedCollectorPlatformError
from cisco_assessment.collector.session.base import NetworkSession
from cisco_assessment.collector.session.cisco_ios import CiscoIOSSession
from cisco_assessment.collector.transport.base import SSHTransport
from cisco_assessment.models import PlatformFamily


class SessionFactory:
    def create(self, *, platform: PlatformFamily, transport: SSHTransport) -> NetworkSession:
        if platform in {PlatformFamily.IOS, PlatformFamily.IOS_XE}:
            return CiscoIOSSession(transport)
        raise UnsupportedCollectorPlatformError(f"unsupported collector platform: {platform}")
