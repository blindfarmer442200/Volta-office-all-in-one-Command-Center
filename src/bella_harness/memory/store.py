"""Read-only stores for Mind Trace memory recall."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, Sequence

from bella_harness.memory.models import MemoryRecord, MemoryValidationError


MAX_STORE_BYTES = 10 * 1024 * 1024
MAX_STORE_RECORDS = 10_000


class MemoryStoreError(RuntimeError):
    """Raised when the memory store cannot be read or validated safely."""


class MemoryStore(Protocol):
    def list_records(self) -> Sequence[MemoryRecord]:
        """Return memory records without applying recall policy."""


class NullMemoryStore:
    def list_records(self) -> Sequence[MemoryRecord]:
        return ()


class InMemoryMemoryStore:
    """Small test/embedding store. It does not persist secrets or state."""

    def __init__(self, records: Sequence[MemoryRecord] | None = None):
        self._records = list(records or ())

    def list_records(self) -> Sequence[MemoryRecord]:
        return tuple(self._records)

    def add(self, record: MemoryRecord) -> None:
        if any(existing.id == record.id for existing in self._records):
            raise MemoryStoreError(f"duplicate memory id: {record.id}")
        self._records.append(record)


class JsonlMemoryStore:
    """Strict, read-only JSONL store for approved memory export files.

    The file is reparsed for each recall so external edits are visible. Any
    malformed line fails the whole read instead of silently skipping evidence.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def list_records(self) -> Sequence[MemoryRecord]:
        try:
            stat = self.path.stat()
        except OSError as exc:
            raise MemoryStoreError(f"memory store is unavailable: {self.path}") from exc
        if not self.path.is_file():
            raise MemoryStoreError(f"memory store is not a regular file: {self.path}")
        if stat.st_size > MAX_STORE_BYTES:
            raise MemoryStoreError("memory store exceeds the 10 MiB safety limit")

        records: list[MemoryRecord] = []
        seen_ids: set[str] = set()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    if len(records) >= MAX_STORE_RECORDS:
                        raise MemoryStoreError(
                            f"memory store exceeds the {MAX_STORE_RECORDS:,} record limit"
                        )
                    try:
                        payload = json.loads(line)
                        record = MemoryRecord.from_dict(payload)
                    except (json.JSONDecodeError, MemoryValidationError) as exc:
                        raise MemoryStoreError(
                            f"invalid memory record at line {line_number}: {exc}"
                        ) from exc
                    if record.id in seen_ids:
                        raise MemoryStoreError(
                            f"duplicate memory id {record.id!r} at line {line_number}"
                        )
                    seen_ids.add(record.id)
                    records.append(record)
        except UnicodeError as exc:
            raise MemoryStoreError("memory store is not valid UTF-8") from exc
        except OSError as exc:
            raise MemoryStoreError(f"could not read memory store: {self.path}") from exc

        return tuple(records)
