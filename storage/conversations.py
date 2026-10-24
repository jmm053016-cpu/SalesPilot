"""使用 SQLite 管理会话、消息及其生命周期关联数据。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models.conversation import Conversation, ConversationMessage, MessageRole
from storage.paths import DEFAULT_RUNTIME_ROOT
from utils.logging_config import get_logger

logger = get_logger(__name__)


# Resolve the default database from the project package rather than the
# process working directory. Streamlit can be launched from another folder.
_DEFAULT_DB_PATH = DEFAULT_RUNTIME_ROOT / "conversations.sqlite3"


class ConversationStore:
    def __init__(self, db_path: Path | str = _DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    dataset_id TEXT,
                    analysis_id TEXT,
                    report_ids_json TEXT NOT NULL DEFAULT '[]',
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_session_updated
                    ON conversations (session_id, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id),
                    UNIQUE (conversation_id, sequence_no)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_sequence
                    ON conversation_messages (conversation_id, sequence_no);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _row_to_conversation(row: sqlite3.Row) -> Conversation:
        return Conversation(
            conversation_id=row["conversation_id"],
            session_id=row["session_id"],
            title=row["title"],
            dataset_id=row["dataset_id"],
            analysis_id=row["analysis_id"],
            report_ids=json.loads(row["report_ids_json"]),
            thread_id=row["thread_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> ConversationMessage:
        return ConversationMessage(
            message_id=row["message_id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            sequence_no=row["sequence_no"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"]),
        )

    def _get_row(self, session_id: str, conversation_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT * FROM conversations
                WHERE session_id = ? AND conversation_id = ? AND status <> 'deleted'
                """,
                (session_id, conversation_id),
            ).fetchone()

    def _require_active(self, session_id: str, conversation_id: str) -> sqlite3.Row:
        row = self._get_row(session_id, conversation_id)
        if row is None:
            raise PermissionError("conversation does not belong to session")
        if row["status"] != "active":
            raise PermissionError("conversation is not active")
        return row

    def create(self, session_id: str, *, title: str = "新建会话") -> Conversation:
        if not session_id:
            raise ValueError("session_id is required")
        created_at = self._now()
        conversation = Conversation(
            conversation_id=self._new_id("conv"),
            session_id=session_id,
            title=title,
            thread_id=self._new_id("thread"),
            created_at=created_at,
            updated_at=created_at,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (
                    conversation_id, session_id, title, dataset_id, analysis_id,
                    report_ids_json, thread_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation.conversation_id,
                    conversation.session_id,
                    conversation.title,
                    conversation.dataset_id,
                    conversation.analysis_id,
                    json.dumps(conversation.report_ids, ensure_ascii=False),
                    conversation.thread_id,
                    conversation.status,
                    conversation.created_at,
                    conversation.updated_at,
                ),
            )
        logger.info("conversation.created | 会话创建完成 | 会话ID=%s | 状态=active | 标题长度=%d", conversation.conversation_id, len(conversation.title))
        return conversation

    def get(self, session_id: str, conversation_id: str) -> Conversation | None:
        row = self._get_row(session_id, conversation_id)
        return self._row_to_conversation(row) if row is not None else None

    def list_history(self, session_id: str) -> list[Conversation]:
        """List non-deleted conversations, including archived read-only history."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversations
                WHERE session_id = ? AND status <> 'deleted'
                ORDER BY updated_at DESC, conversation_id DESC
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_conversation(row) for row in rows]

    def list_all_history(self) -> list[Conversation]:
        """List non-deleted conversations across all local workspaces."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversations
                WHERE status <> 'deleted'
                ORDER BY updated_at DESC, conversation_id DESC
                """
            ).fetchall()
        return [self._row_to_conversation(row) for row in rows]

    def get_by_id(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by its globally unique ID and retain its owner session."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return self._row_to_conversation(row) if row is not None else None

    def list_active(self, session_id: str) -> list[Conversation]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversations
                WHERE session_id = ? AND status = 'active'
                ORDER BY updated_at DESC, conversation_id DESC
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_conversation(row) for row in rows]

    def update_title(self, session_id: str, conversation_id: str, title: str) -> Conversation:
        try:
            self._require_active(session_id, conversation_id)
            if not title.strip():
                raise ValueError("title is required")
            updated_at = self._now()
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE conversations SET title = ?, updated_at = ?
                    WHERE session_id = ? AND conversation_id = ? AND status = 'active'
                    """,
                    (title.strip(), updated_at, session_id, conversation_id),
                )
            updated = self.get(session_id, conversation_id)
        except Exception as exc:
            logger.warning("conversation.renamed.failed | 会话重命名失败 | 会话ID=%s | 异常类型=%s", conversation_id, type(exc).__name__)
            raise
        logger.info("conversation.renamed | 会话重命名完成 | 会话ID=%s | 状态=active | 新标题长度=%d", conversation_id, len(updated.title))
        return updated  # type: ignore[return-value]

    def bind_resources(
        self,
        session_id: str,
        conversation_id: str,
        *,
        dataset_id: str | None,
        analysis_id: str | None,
        report_ids: list[str],
        thread_id: str,
    ) -> Conversation:
        self._require_active(session_id, conversation_id)
        if not thread_id:
            raise ValueError("thread_id is required")
        updated_at = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE conversations
                SET dataset_id = ?, analysis_id = ?, report_ids_json = ?,
                    thread_id = ?, updated_at = ?
                WHERE session_id = ? AND conversation_id = ? AND status = 'active'
                """,
                (
                    dataset_id,
                    analysis_id,
                    json.dumps(list(report_ids), ensure_ascii=False),
                    thread_id,
                    updated_at,
                    session_id,
                    conversation_id,
                ),
            )
        updated = self.get(session_id, conversation_id)
        logger.info(
            "conversation.resources.bound | 会话资源绑定完成 | 会话ID=%s | 数据集已绑定=%s | 分析已绑定=%s | 报告数量=%d | 追问线程已绑定=%s",
            conversation_id,
            dataset_id is not None,
            analysis_id is not None,
            len(report_ids),
            bool(thread_id),
        )
        return updated  # type: ignore[return-value]

    def append_message(
        self,
        session_id: str,
        conversation_id: str,
        *,
        role: MessageRole,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        self._require_active(session_id, conversation_id)
        created_at = self._now()
        message_id = self._new_id("msg")
        with self._connect() as connection:
            next_sequence = connection.execute(
                """
                SELECT COALESCE(MAX(sequence_no), 0) + 1
                FROM conversation_messages
                WHERE session_id = ? AND conversation_id = ?
                """,
                (session_id, conversation_id),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO conversation_messages (
                    message_id, conversation_id, session_id, role, content,
                    sequence_no, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    session_id,
                    role,
                    content,
                    next_sequence,
                    created_at,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE session_id = ? AND conversation_id = ?",
                (created_at, session_id, conversation_id),
            )
        message = ConversationMessage(
            message_id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            sequence_no=next_sequence,
            created_at=created_at,
            metadata=metadata or {},
        )
        logger.info("conversation.message.appended | 会话消息已保存 | 会话ID=%s | 角色=%s | 序号=%d | 内容长度=%d", conversation_id, role, message.sequence_no, len(content))
        return message

    def list_messages(self, session_id: str, conversation_id: str) -> list[ConversationMessage]:
        conversation = self.get(session_id, conversation_id)
        if conversation is None:
            raise PermissionError("conversation does not belong to session")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversation_messages
                WHERE session_id = ? AND conversation_id = ?
                ORDER BY sequence_no ASC
                """,
                (session_id, conversation_id),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def archive(self, session_id: str, conversation_id: str) -> Conversation:
        """Archive a conversation without removing its messages or resources."""
        try:
            self._require_active(session_id, conversation_id)
            updated_at = self._now()
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE conversations
                    SET status = 'archived', updated_at = ?
                    WHERE session_id = ? AND conversation_id = ? AND status = 'active'
                    """,
                    (updated_at, session_id, conversation_id),
                )
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM conversations
                    WHERE session_id = ? AND conversation_id = ?
                    """,
                    (session_id, conversation_id),
                ).fetchone()
            archived = self._row_to_conversation(row)  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("conversation.archived.failed | 会话归档失败 | 会话ID=%s | 异常类型=%s", conversation_id, type(exc).__name__)
            raise
        logger.info("conversation.archived | 会话已归档 | 会话ID=%s | 原状态=active | 当前状态=%s | 归档后只读=true", conversation_id, archived.status)
        return archived

    def unarchive(self, session_id: str, conversation_id: str) -> Conversation:
        """Restore an archived conversation to the active, writable state."""
        row = self._get_row(session_id, conversation_id)
        if row is None:
            raise PermissionError("conversation does not belong to session")
        if row["status"] != "archived":
            raise PermissionError("conversation is not archived")

        updated_at = self._now()
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE conversations
                SET status = 'active', updated_at = ?
                WHERE session_id = ? AND conversation_id = ? AND status = 'archived'
                """,
                (updated_at, session_id, conversation_id),
            )
            if result.rowcount != 1:
                raise PermissionError("conversation is not archived")
            restored_row = connection.execute(
                "SELECT * FROM conversations WHERE session_id = ? AND conversation_id = ?",
                (session_id, conversation_id),
            ).fetchone()
        restored = self._row_to_conversation(restored_row)  # type: ignore[arg-type]
        logger.info(
            "conversation.unarchived | 会话已取消归档 | 会话ID=%s | 原状态=archived | 当前状态=active",
            conversation_id,
        )
        return restored

    def soft_delete(self, session_id: str, conversation_id: str) -> None:
        # Archived conversations are read-only, but they remain deletable.
        try:
            row = self._get_row(session_id, conversation_id)
            if row is None:
                raise PermissionError("conversation does not belong to session")
            previous_status = row["status"]
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE conversations
                    SET status = 'deleted', updated_at = ?
                    WHERE session_id = ? AND conversation_id = ? AND status <> 'deleted'
                    """,
                    (self._now(), session_id, conversation_id),
                )
                connection.execute(
                    "DELETE FROM conversation_messages WHERE session_id = ? AND conversation_id = ?",
                    (session_id, conversation_id),
                )
        except Exception as exc:
            logger.warning("conversation.deleted.failed | 会话删除失败 | 会话ID=%s | 异常类型=%s", conversation_id, type(exc).__name__)
            raise
        logger.info("conversation.deleted | 会话已删除 | 会话ID=%s | 原状态=%s | 当前状态=deleted", conversation_id, previous_status)
