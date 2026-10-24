"""Agent 状态与可替换的短期记忆检查点抽象。"""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, TypedDict

try:
    from langgraph.checkpoint.memory import InMemorySaver as _GraphInMemorySaver
    _HAS_LANGGRAPH = True
except ImportError:  # pragma: no cover - optional compatibility
    _GraphInMemorySaver = object
    _HAS_LANGGRAPH = False

try:  # LangGraph 1.x 提供框架状态基类；缺少该模块时使用兼容 fallback。
    from langchain.agents import AgentState as _FrameworkAgentState
except ImportError:  # pragma: no cover - only exercised in minimal environments
    class _FrameworkAgentState(TypedDict, total=False):
        messages: list[Any]


class AgentState(_FrameworkAgentState, total=False):
    """追问 Agent 使用的状态契约。

    ``messages`` 由框架负责 reducer；业务引用只保存服务端 ID，不保存原始表或绝对路径。
    """

    dataset_id: str
    analysis_id: str
    report_id: str
    session_id: str
    thread_id: str


class Checkpointer:
    """检查点存储接口，后续可替换为 LangGraph 持久化实现。"""

    def get(self, *, session_id: str, thread_id: str) -> AgentState | None:
        raise NotImplementedError

    def put(self, *, session_id: str, thread_id: str, state: AgentState) -> None:
        raise NotImplementedError

    def delete(self, *, session_id: str, thread_id: str) -> None:
        raise NotImplementedError


class InMemorySaver(_GraphInMemorySaver, Checkpointer):
    """Session-scoped app saver with the LangGraph in-memory saver protocol."""

    def __init__(self) -> None:
        if _HAS_LANGGRAPH:
            super().__init__()
        self._states: dict[tuple[str, str], AgentState] = {}
        self._lock = RLock()

    def _key(self, session_id: str, thread_id: str) -> tuple[str, str]:
        if not session_id or not thread_id:
            raise ValueError("session_id and thread_id are required")
        return session_id, thread_id

    def get(self, config: Any = None, *, session_id: str | None = None,
            thread_id: str | None = None) -> Any:
        if session_id is not None and thread_id is not None:
            with self._lock:
                state = self._states.get(self._key(session_id, thread_id))
                return deepcopy(state) if state is not None else None
        if not _HAS_LANGGRAPH:
            raise TypeError("session_id and thread_id are required")
        return super().get(config)

    def put(self, config: Any = None, checkpoint: Any = None, metadata: Any = None,
            new_versions: Any = None, *, session_id: str | None = None,
            thread_id: str | None = None, state: AgentState | None = None) -> Any:
        if session_id is not None and thread_id is not None and state is not None:
            key = self._key(session_id, thread_id)
            with self._lock:
                self._states[key] = deepcopy(dict(state))
            return None
        if not _HAS_LANGGRAPH:
            raise TypeError("session_id, thread_id, and state are required")
        return super().put(config, checkpoint, metadata, new_versions)

    def delete(self, *, session_id: str, thread_id: str) -> None:
        with self._lock:
            self._states.pop(self._key(session_id, thread_id), None)
        if _HAS_LANGGRAPH:
            self.delete_thread(_graph_thread_id(session_id, thread_id))


def _graph_thread_id(session_id: str, thread_id: str) -> str:
    import json

    return json.dumps([session_id, thread_id], separators=(",", ":"))