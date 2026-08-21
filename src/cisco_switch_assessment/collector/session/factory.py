from cisco_switch_assessment.collector.session.cisco_ios import CiscoIOSSession
from cisco_switch_assessment.collector.transport.base import SSHTransport
from cisco_switch_assessment.models import Platform

class SessionFactory:
    def create(self, platform: Platform, transport: SSHTransport) -> CiscoIOSSession:
        if platform in {Platform.IOS, Platform.IOS_XE}:
            return CiscoIOSSession(transport)
        raise ValueError(f"unsupported collector platform: {platform}")
