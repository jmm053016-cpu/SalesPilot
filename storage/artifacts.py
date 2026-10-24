"""登记报告等文件产物，并限制其会话级访问范围。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from storage.paths import DEFAULT_RUNTIME_ROOT


class UnauthorizedArtifactError(PermissionError):
    pass


class ArtifactStore:
    def __init__(self, root: Path | str = DEFAULT_RUNTIME_ROOT / "artifacts") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _valid(value: str) -> None:
        if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError("invalid storage identifier")

    def register(self, session_id: str, artifact_id: str, artifact: Any) -> None:
        self._valid(session_id)
        self._valid(artifact_id)
        folder = self.root / session_id
        folder.mkdir(parents=True, exist_ok=True)
        payload = artifact.model_dump(mode="json") if hasattr(artifact, "model_dump") else artifact
        (folder / f"{artifact_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def resolve(self, session_id: str, artifact_id: str) -> dict[str, Any]:
        self._valid(session_id)
        self._valid(artifact_id)
        path = self.root / session_id / f"{artifact_id}.json"
        if not path.is_file():
            raise UnauthorizedArtifactError("artifact does not belong to session")
        return json.loads(path.read_text(encoding="utf-8"))
    def delete(self, session_id: str, artifact_id: str) -> None:
        self._valid(session_id)
        self._valid(artifact_id)
        path = self.root / session_id / f"{artifact_id}.json"
        if path.exists():
            path.unlink()
