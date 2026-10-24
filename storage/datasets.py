"""保存标准化数据集，并通过会话身份执行访问隔离。"""

from __future__ import annotations

import json
import re
import hashlib
import threading
import uuid
from pathlib import Path

import pandas as pd

from models.sales import DatasetProfile, DatasetRef
from storage.paths import DEFAULT_RUNTIME_ROOT


class UnauthorizedDatasetError(PermissionError):
    """Raised when a dataset is not owned by the requesting session."""


class DatasetStore:
    _idempotency_lock = threading.RLock()

    def __init__(self, root: Path | str = DEFAULT_RUNTIME_ROOT) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_segment(value: str, name: str) -> None:
        if not value or re.fullmatch(r'[A-Za-z0-9_-]+', value) is None:
            raise ValueError(f'invalid {name}')

    def _session_root(self, session_id: str) -> Path:
        self._validate_segment(session_id, 'session_id')
        session_root = (self.root / session_id).resolve()
        if session_root.parent != self.root:
            raise ValueError('session path escapes store root')
        return session_root

    def save(self, session_id: str, df: pd.DataFrame, profile: DatasetProfile) -> DatasetRef:
        if profile.session_id != session_id:
            raise UnauthorizedDatasetError('profile does not belong to session')
        session_root = self._session_root(session_id)
        dataset_id = f'ds_{uuid.uuid4().hex}'
        dataset_root = (session_root / dataset_id).resolve()
        if dataset_root.parent != session_root:
            raise ValueError('dataset path escapes session root')
        dataset_root.mkdir(parents=True, exist_ok=False)
        data_path = dataset_root / 'data.csv'
        metadata_path = dataset_root / 'metadata.json'
        df.to_csv(data_path, index=False, encoding='utf-8')
        metadata = profile.model_copy(update={'dataset_id': dataset_id}).model_dump(mode='json')
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        return DatasetRef(dataset_id=dataset_id, session_id=session_id, storage_key=f'{session_id}/{dataset_id}')

    def save_idempotent(
        self,
        session_id: str,
        df: pd.DataFrame,
        profile: DatasetProfile,
        *,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> DatasetRef:
        """Persist an import once per session/key and reject key reuse for other input."""
        if not idempotency_key or not request_fingerprint:
            raise ValueError('idempotency key and request fingerprint are required')
        session_root = self._session_root(session_id)
        session_root.mkdir(parents=True, exist_ok=True)
        index_path = session_root / 'import_idempotency.json'
        key_hash = hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()
        with self._idempotency_lock:
            index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
            existing = index.get(key_hash)
            if existing:
                if existing.get('fingerprint') != request_fingerprint:
                    raise ValueError('idempotency key was already used for a different import')
                dataset_id = existing.get('dataset_id', '')
                self.load(session_id, dataset_id)
                return DatasetRef(
                    dataset_id=dataset_id,
                    session_id=session_id,
                    storage_key=f'{session_id}/{dataset_id}',
                )

            reference = self.save(session_id, df, profile)
            index[key_hash] = {
                'fingerprint': request_fingerprint,
                'dataset_id': reference.dataset_id,
            }
            temporary = index_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
            temporary.replace(index_path)
            return reference

    def load(self, session_id: str, dataset_id: str) -> pd.DataFrame:
        self._validate_segment(dataset_id, 'dataset_id')
        session_root = self._session_root(session_id)
        dataset_root = (session_root / dataset_id).resolve()
        if dataset_root.parent != session_root or not dataset_root.is_dir():
            raise UnauthorizedDatasetError('dataset does not belong to session')
        metadata_path = dataset_root / 'metadata.json'
        data_path = dataset_root / 'data.csv'
        if not metadata_path.is_file() or not data_path.is_file():
            raise UnauthorizedDatasetError('dataset artifacts are incomplete')
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        if metadata.get('session_id') != session_id or metadata.get('dataset_id') != dataset_id:
            raise UnauthorizedDatasetError('dataset ownership metadata mismatch')
        return pd.read_csv(data_path, encoding='utf-8', dtype={field: str for field in ('sales_amount', 'refund_amount', 'cost_amount')})
