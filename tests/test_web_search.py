from __future__ import annotations

import sys
import types

from agent.web_search import create_web_search_tool


def test_web_search_is_disabled_without_tavily_key(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    assert create_web_search_tool() is None


def test_web_search_builds_controlled_tavily_tool(monkeypatch) -> None:
    captured = {}

    class FakeTavilySearch:
        name = "tavily_search"

        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
    monkeypatch.setitem(
        sys.modules,
        "langchain_tavily",
        types.SimpleNamespace(TavilySearch=FakeTavilySearch),
    )

    tool = create_web_search_tool()

    assert tool is not None
    assert tool.name == "tavily_search"
    assert captured == {
        "max_results": 5,
        "topic": "general",
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }


def test_create_agent_registers_search_only_when_available(monkeypatch) -> None:
    import agent.analysis_tools
    import agent.agent_setup as setup

    base_tools = [object()]
    search_tool = object()
    captured = {}
    monkeypatch.setattr(agent.analysis_tools, "create_analysis_tools", lambda **kwargs: base_tools.copy())
    monkeypatch.setattr(setup, "create_agent_runtime", lambda *, tools: captured.setdefault("tools", tools))
    monkeypatch.setattr("agent.web_search.create_web_search_tool", lambda: search_tool)

    setup.create_agent()

    assert captured["tools"] == [base_tools[0], search_tool]


def test_create_agent_keeps_local_tools_when_search_is_unavailable(monkeypatch) -> None:
    import agent.analysis_tools
    import agent.agent_setup as setup

    base_tools = [object()]
    captured = {}
    monkeypatch.setattr(agent.analysis_tools, "create_analysis_tools", lambda **kwargs: base_tools.copy())
    monkeypatch.setattr(setup, "create_agent_runtime", lambda *, tools: captured.setdefault("tools", tools))
    monkeypatch.setattr("agent.web_search.create_web_search_tool", lambda: None)

    setup.create_agent()

    assert captured["tools"] == base_tools
