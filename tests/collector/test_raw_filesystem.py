import hashlib
from cisco_switch_assessment.catalog import MVP_COMMAND_CATALOG, CommandId
from cisco_switch_assessment.collector.raw.filesystem import FilesystemRawRepository
from cisco_switch_assessment.models import CommandExecution

def test_filesystem_repository_preserves_exact_bytes(tmp_path):
    raw=b"line1\r\nline2  \r\n\x00\xff\x1b[0m"; repository=FilesystemRawRepository(tmp_path); execution_id=CommandExecution.new_id()
    artifact=repository.save(run_id="run-001", device_id="sw-core-01", execution_id=execution_id, command=MVP_COMMAND_CATALOG.get(CommandId.SHOW_VERSION), content=raw)
    assert artifact.storage_path.read_bytes() == raw; assert artifact.size_bytes == len(raw); assert artifact.sha256 == hashlib.sha256(raw).hexdigest()
