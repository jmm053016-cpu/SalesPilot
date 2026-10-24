"""管理 Agent 工具调用所需的会话身份和线程运行时上下文。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    session_id: str
    thread_id: str

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.thread_id:
            raise ValueError("thread_id is required")


_current_context: ContextVar[RuntimeContext | None] = ContextVar(
    "salespilot_agent_runtime_context", default=None
)


def get_runtime_context() -> RuntimeContext | None:
    """返回当前异步/线程上下文；没有运行上下文时返回 None。"""

    return _current_context.get()


def require_runtime_context() -> RuntimeContext:
    context = get_runtime_context()
    if context is None:
        raise RuntimeError("agent runtime context is not set")
    return context


@contextmanager
def runtime_context(session_id: str, thread_id: str) -> Iterator[RuntimeContext]:
    """在一次 Agent 调用期间绑定会话身份，退出时恢复上层上下文。"""

    context = RuntimeContext(session_id=session_id, thread_id=thread_id)
    token = _current_context.set(context)
    try:
        yield context
    finally:
        _current_context.reset(token)
