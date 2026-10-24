"""Store uploaded source files behind session-owned server-side references."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from data_sources.import_service import SourceSelection
from storage.paths import DEFAULT_RUNTIME_ROOT


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    filename: str
    kind: str
    size_bytes: int


class UploadStore:
    DEFAULT_SUFFIXES = {".csv", ".xlsx", ".xlsm", ".db", ".sqlite", ".sqlite3"}
    _lock = threading.RLock()

    def __init__(
        self,
        root: Path | str = DEFAULT_RUNTIME_ROOT / "uploads",
        max_bytes: int = 20 * 1024 * 1024,
        allowed_suffixes: set[str] | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.allowed_suffixes = {
            suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
            for suffix in (allowed_suffixes or self.DEFAULT_SUFFIXES)
        }

    @staticmethod
    def _session_root(session_id: str) -> Path:
        if re.fullmatch(r"[A-Za-z0-9_-]+", session_id or "") is None:
            raise ValueError("invalid session_id")
        return session_id

    def _metadata_path(self, session_id: str) -> Path:
        return self.root / self._session_root(session_id) / "sources.json"

    def save(self, session_id: str, filename: str, content: bytes, source_key: str) -> SourceRef:
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")
        if not content:
            raise ValueError("uploaded file is empty")
        if len(content) > self.max_bytes:
            raise ValueError(f"uploaded file exceeds size limit of {self.max_bytes} bytes")
        safe_name = PureWindowsPath(str(filename)).name
        suffix = Path(safe_name).suffix.lower()
        if not safe_name or suffix not in self.allowed_suffixes:
            raise ValueError("unsupported file extension")
        if not source_key or len(source_key) > 200:
            raise ValueError("invalid source_key")

        session_root = self.root / self._session_root(session_id)
        session_root.mkdir(parents=True, exist_ok=True)
        metadata_path = self._metadata_path(session_id)
        kind = "csv" if suffix == ".csv" else "excel" if suffix in {".xlsx", ".xlsm"} else "sqlite"
        key_hash = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
        with self._lock:
            records = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            existing_id = records.get("keys", {}).get(key_hash)
            if existing_id:
                metadata = records["sources"].get(existing_id)
                if metadata:
                    return SourceRef(**metadata)

            source_id = f"src_{uuid.uuid4().hex}"
            metadata = {
                "source_id": source_id,
                "filename": safe_name,
                "kind": kind,
                "size_bytes": len(content),
            }
            source_path = session_root / f"{source_id}{suffix}"
            source_path.write_bytes(content)
            records.setdefault("sources", {})[source_id] = metadata
            records.setdefault("keys", {})[key_hash] = source_id
            temporary = metadata_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
            temporary.replace(metadata_path)
        return SourceRef(**metadata)

    def resolve(self, session_id: str, source_id: str) -> SourceSelection:
        if re.fullmatch(r"src_[a-f0-9]{32}", source_id or "") is None:
            raise ValueError("invalid source_id")
        metadata_path = self._metadata_path(session_id)
        if not metadata_path.is_file():
            raise PermissionError("source does not belong to this session")
        records = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata = records.get("sources", {}).get(source_id)
        if metadata is None:
            raise PermissionError("source does not belong to this session")
        suffix = Path(metadata["filename"]).suffix.lower()
        source_path = (self.root / self._session_root(session_id) / f"{source_id}{suffix}").resolve()
        if source_path.parent != self.root / session_id or not source_path.is_file():
            raise PermissionError("source artifact is unavailable")
        return SourceSelection(
            kind=metadata["kind"],
            path=source_path,
            sheet_name=0 if metadata["kind"] == "excel" else None,
            query_name="orders" if metadata["kind"] == "sqlite" else None,
        )
