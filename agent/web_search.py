"""可选的 Tavily 外部网页搜索工具。"""

from __future__ import annotations

import os
from typing import Any


def create_web_search_tool() -> Any | None:
    """Create the bounded Tavily tool when external search is configured.

    Web search is optional so local import and deterministic analysis remain
    available when the API key or optional package is not configured.
    """

    if not os.environ.get("TAVILY_API_KEY"):
        return None
    try:
        from langchain_tavily import TavilySearch
    except ImportError:
        return None
    return TavilySearch(
        max_results=5,
        topic="general",
        search_depth="basic",
        include_answer=False,
        include_raw_content=False,
    )
