"""生成并缓存数据集画像，供分析配置与工具调用复用。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from models.sales import DatasetProfile

from .datasets import DatasetStore


def _profile_for(dataset_store: DatasetStore, session_id: str, dataset_id: str) -> DatasetProfile:
    session_root = dataset_store._session_root(session_id)
    metadata_path = session_root / dataset_id / "metadata.json"
    if not metadata_path.is_file():
        raise PermissionError("dataset profile does not belong to session")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("session_id") != session_id or metadata.get("dataset_id") != dataset_id:
        raise PermissionError("dataset ownership metadata mismatch")
    return DatasetProfile.model_validate(metadata)


def load_dataset_profile(dataset_store: DatasetStore, session_id: str, dataset_id: str) -> DatasetProfile:
    return _profile_for(dataset_store, session_id, dataset_id)
