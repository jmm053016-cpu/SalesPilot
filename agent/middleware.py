"""为真实与测试 Agent 后端提供一致的运行时输入保护。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from contextvars import copy_context
from time import monotonic
from typing import Any, Callable, Iterator


class ToolCallLimitError(RuntimeError):
    pass


class ModelTimeoutError(TimeoutError):
    pass


def call_with_timeout(fn: Callable[[], Any], timeout_seconds: float) -> Any:
    """Run a synchronous call with a real wall-clock deadline.

    Python cannot forcibly stop a running worker thread, but the caller returns
    at the deadline and the worker is cancelled when possible. This keeps the
    agent request from waiting for an unresponsive model.
    """
    if timeout_seconds <= 0:
        return fn()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(copy_context().run, fn)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise ModelTimeoutError("model timeout / 模型超时") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


@contextmanager
def model_deadline(timeout_seconds: float) -> Iterator[None]:
    """Compatibility context for callers that need elapsed-time validation."""
    started = monotonic()
    yield
    if timeout_seconds > 0 and monotonic() - started > timeout_seconds:
        raise ModelTimeoutError("model timeout / 模型超时")


def ensure_tool_budget(tool_calls: int, max_tool_calls: int) -> None:
    if max_tool_calls >= 0 and tool_calls > max_tool_calls:
        raise ToolCallLimitError("tool call limit exceeded / 工具调用次数超限")


def count_tool_calls(messages: list[Any]) -> int:
    """Count model-emitted tool calls in a LangChain message history."""
    total = 0
    for message in messages:
        total += len(getattr(message, "tool_calls", None) or [])
    return total
