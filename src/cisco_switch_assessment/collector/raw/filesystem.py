from __future__ import annotations
import hashlib, os, tempfile
from pathlib import Path
from uuid import UUID
from cisco_switch_assessment.catalog import CommandSpec
from cisco_switch_assessment.collector.exceptions import RawPersistenceError
from cisco_switch_assessment.models import RawCommandOutput, utcnow

def _safe_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)
    if not cleaned or cleaned in {".", ".."}: raise RawPersistenceError("invalid RAW path component")
    return cleaned

class FilesystemRawRepository:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def save(self, *, run_id: str, device_id: str, execution_id: UUID, command: CommandSpec, content: bytes) -> RawCommandOutput:
        directory = self._root / _safe_component(run_id) / "devices" / _safe_component(device_id) / "raw"
        filename = f"{execution_id}_{_safe_component(command.id.value)}.raw"
        final_path = directory / filename
        digest = hashlib.sha256(content).hexdigest()
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp_name = tempfile.mkstemp(prefix=f".{filename}.", dir=directory)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content); handle.flush(); os.fsync(handle.fileno())
                os.chmod(tmp_name, 0o600)
                os.replace(tmp_name, final_path)
            except Exception:
                try: os.unlink(tmp_name)
                except FileNotFoundError: pass
                raise
        except OSError as exc:
            raise RawPersistenceError(f"failed to persist RAW output: {exc}") from exc
        return RawCommandOutput(id=RawCommandOutput.new_id(), command_execution_id=execution_id, storage_path=final_path, size_bytes=len(content), sha256=digest, captured_at=utcnow())
