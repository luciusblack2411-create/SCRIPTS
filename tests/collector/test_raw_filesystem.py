import hashlib
from uuid import uuid4

from cisco_assessment.raw import FilesystemRawRepository


def test_filesystem_repository_preserves_bytes_and_model_round_trip(tmp_path) -> None:
    raw = b"line1\r\nline2  \r\n\x00\xff\x1b[0m"
    repository = FilesystemRawRepository(tmp_path)

    artifact = repository.save(
        assessment_run_id=uuid4(),
        device_id=uuid4(),
        command_execution_id=uuid4(),
        command_key="system.version",
        sequence=1,
        content=raw,
    )

    assert artifact.path.read_bytes() == raw
    assert artifact.output.content.encode(artifact.output.encoding) == raw
    assert artifact.output.sha256 == hashlib.sha256(raw).hexdigest()
    assert artifact.output.byte_length == len(raw)
