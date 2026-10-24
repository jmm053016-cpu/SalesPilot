"""在会话隔离边界内保存和读取结构化分析结果。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from storage.paths import DEFAULT_RUNTIME_ROOT


class UnauthorizedAnalysisError(PermissionError):
    pass


class AnalysisStore:
    def __init__(self, root: Path | str = DEFAULT_RUNTIME_ROOT / "analyses") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _valid(value: str) -> None:
        if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError("invalid storage identifier")

    def save(self, session_id: str, analysis_id: str, analysis: Any) -> None:
        self._valid(session_id)
        self._valid(analysis_id)
        folder = self.root / session_id
        folder.mkdir(parents=True, exist_ok=True)
        payload = analysis.model_dump(mode="json") if hasattr(analysis, "model_dump") else analysis
        (folder / f"{analysis_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, session_id: str, analysis_id: str) -> dict[str, Any]:
        self._valid(session_id)
        self._valid(analysis_id)
        path = self.root / session_id / f"{analysis_id}.json"
        if not path.is_file():
            raise UnauthorizedAnalysisError("analysis does not belong to session")
        return json.loads(path.read_text(encoding="utf-8"))
    def delete(self, session_id: str, analysis_id: str) -> None:
        self._valid(session_id)
        self._valid(analysis_id)
        path = self.root / session_id / f"{analysis_id}.json"
        if path.exists():
            path.unlink()
