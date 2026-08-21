from collections import deque
from cisco_switch_assessment.collector.session.cisco_ios import CiscoIOSSession

class ScriptedTransport:
    def __init__(self, chunks): self.chunks=deque(chunks); self.sent=[]
    def send(self, data): self.sent.append(data)
    def receive_ready(self): return bool(self.chunks)
    def receive(self, max_bytes=65535): return self.chunks.popleft()
    def close(self): pass

def test_execute_returns_exact_received_chunks_without_normalization():
    chunks=[b"show version\r\nCisco IOS ", b"XE Software  \r\nSW1#"]; transport=ScriptedTransport(chunks.copy()); session=CiscoIOSSession(transport, sleeper=lambda _: None)
    result=session.execute("show version", timeout=1.0)
    assert transport.sent == [b"show version\n"]; assert result.raw == b"".join(chunks)

def test_prompt_like_line_inside_output_does_not_end_capture_early():
    chunks=[b"show version\r\nNotARealPrompt#\r\nmore output\r\n", b"SW1#"]; transport=ScriptedTransport(chunks.copy()); session=CiscoIOSSession(transport, sleeper=lambda _: None)
    assert session.execute("show version", timeout=1.0).raw == b"".join(chunks)
