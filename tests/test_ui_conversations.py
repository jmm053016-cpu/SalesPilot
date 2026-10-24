from pathlib import Path

from models.conversation import ConversationMessage
from storage.conversations import ConversationStore
from ui.session import AnalysisSession


def test_derive_conversation_title_uses_first_line_and_truncates():
    from ui.conversations import derive_conversation_title

    title = derive_conversation_title("  第一行问题很长很长很长很长很长很长很长很长\n第二行")

    assert title.startswith("第一行问题")
    assert "第二行" not in title
    assert len(title) <= 32


def test_derive_conversation_title_defaults_for_blank_question():
    from ui.conversations import derive_conversation_title

    assert derive_conversation_title("  \n") == "新建会话"


def test_create_new_conversation_uses_question_title(tmp_path):
    from ui.conversations import create_new_conversation

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = create_new_conversation(store, "session-a", question="利润为什么下降？")

    assert conversation.title == "利润为什么下降？"
    assert conversation.session_id == "session-a"


def test_switch_conversation_restores_resources_and_thread(tmp_path):
    from ui.conversations import switch_conversation

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a", title="历史会话")
    store.bind_resources(
        "session-a", conversation.conversation_id,
        dataset_id="ds-1", analysis_id="analysis-1", report_ids=["report-1"],
        thread_id="thread-history",
    )

    session = switch_conversation(store, "session-a", conversation.conversation_id)

    assert session == AnalysisSession(
        session_id="session-a", conversation_id=conversation.conversation_id,
        dataset_id="ds-1", analysis_id="analysis-1", report_ids=["report-1"],
        thread_id="thread-history",
    )


def test_switch_state_clears_previous_page_cache():
    from ui.conversations import reset_conversation_view_state

    state = {
        "followup_messages": [{"role": "user", "content": "旧问题"}],
        "followup_events": ["old-event"],
        "analysis_result": "old-result",
        "analysis_report": "old-report",
    }

    reset_conversation_view_state(state)

    assert state["followup_messages"] == []
    assert state["followup_events"] == []
    assert state["analysis_result"] is None
    assert state["analysis_report"] is None


def test_switch_conversation_logs_status_without_message_content(tmp_path, caplog):
    import logging

    from ui.conversations import switch_conversation

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a", title="历史会话")
    logger = logging.getLogger("salespilot.ui.conversations")
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.INFO)
    try:
        switch_conversation(store, "session-a", conversation.conversation_id)
    finally:
        logger.removeHandler(caplog.handler)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "conversation.switched" in messages
    assert conversation.conversation_id in messages
    assert "历史会话" not in messages


def test_render_conversation_messages_uses_message_roles(monkeypatch):
    from ui.conversations import render_conversation_messages

    calls = []
    class Chat:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    class FakeStreamlit:
        def chat_message(self, role):
            calls.append(("chat_message", role))
            return Chat()
        def markdown(self, content):
            calls.append(("markdown", content))

    monkeypatch.setitem(__import__("sys").modules, "streamlit", FakeStreamlit())
    render_conversation_messages([
        ConversationMessage("m1", "c1", "user", "问题", 1, "now"),
        ConversationMessage("m2", "c1", "assistant", "回答", 2, "now"),
        ConversationMessage("m3", "c1", "error", "错误", 3, "now"),
    ])

    assert [call for call in calls if call[0] == "chat_message"] == [
        ("chat_message", "user"), ("chat_message", "assistant"), ("chat_message", "error")
    ]


def test_renaming_conversation_reruns_page_to_refresh_title_and_controls(tmp_path, monkeypatch):
    import sys

    from ui.conversations import render_conversation_sidebar

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a", title="old-title")
    calls = []

    class FakeStreamlit:
        def markdown(self, *args, **kwargs):
            pass

        def button(self, label, **kwargs):
            return label == "保存名称"

        def selectbox(self, *args, **kwargs):
            return conversation.conversation_id

        def text_input(self, *args, **kwargs):
            return "" if kwargs.get("key") == "conversation_search" else "new-title"

        def caption(self, *args, **kwargs):
            pass

        def rerun(self):
            calls.append("rerun")

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())

    render_conversation_sidebar(store, "session-a", conversation.conversation_id)

    assert store.get("session-a", conversation.conversation_id).title == "new-title"
    assert calls == ["rerun"]


def test_archived_sidebar_offers_one_click_unarchive_and_reruns(tmp_path, monkeypatch):
    import sys

    from ui.conversations import render_conversation_sidebar

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a", title="历史会话")
    store.archive("session-a", conversation.conversation_id)
    calls = []

    class FakeStreamlit:
        def markdown(self, *args, **kwargs):
            pass

        def caption(self, *args, **kwargs):
            pass

        def button(self, label, **kwargs):
            return label == "取消归档"

        def text_input(self, label, value="", **kwargs):
            return "" if kwargs.get("key") == "conversation_search" else value

        def rerun(self):
            calls.append("rerun")

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())

    render_conversation_sidebar(store, "session-a", conversation.conversation_id)

    assert store.get("session-a", conversation.conversation_id).status == "active"
    assert calls == ["rerun"]


def test_active_sidebar_archives_with_one_click(tmp_path, monkeypatch):
    import sys

    from ui.conversations import render_conversation_sidebar

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a", title="当前会话")
    button_calls = []

    class FakeStreamlit:
        def markdown(self, *args, **kwargs):
            pass

        def text_input(self, *args, **kwargs):
            return "" if kwargs.get("key") == "conversation_search" else conversation.title

        def caption(self, *args, **kwargs):
            pass

        def button(self, label, **kwargs):
            button_calls.append(label)
            return label == "归档当前会话"

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())

    selected = render_conversation_sidebar(store, "session-a", conversation.conversation_id)

    assert selected == conversation.conversation_id
    assert store.get("session-a", conversation.conversation_id).status == "archived"
    assert button_calls.count("归档当前会话") == 1


def test_archive_action_targets_current_conversation_not_stale_selector(tmp_path, monkeypatch):
    import sys

    from ui.conversations import render_conversation_sidebar

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    current = store.create("session-a", title="当前会话")
    other = store.create("session-a", title="另一个会话")
    calls = []

    class FakeStreamlit:
        def markdown(self, *args, **kwargs):
            pass

        def text_input(self, *args, **kwargs):
            return "" if kwargs.get("key") == "conversation_search" else other.title

        def caption(self, *args, **kwargs):
            pass

        def button(self, label, **kwargs):
            return label == "归档当前会话"

        def rerun(self):
            calls.append("rerun")

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())

    selected = render_conversation_sidebar(store, "session-a", current.conversation_id)

    assert selected == current.conversation_id
    assert store.get("session-a", current.conversation_id).status == "archived"
    assert store.get("session-a", other.conversation_id).status == "active"
    assert calls == ["rerun"]


def test_sidebar_lists_conversations_from_all_sessions(tmp_path, monkeypatch):
    import sys

    from ui.conversations import render_conversation_sidebar

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    current = store.create("workspace-current", title="Current workspace")
    historical = store.create("workspace-old", title="Old workspace history")
    shown = {}

    class FakeStreamlit:
        def markdown(self, *args, **kwargs):
            pass

        def button(self, *args, **kwargs):
            key = kwargs.get("key", "")
            if key.startswith("open_conversation_"):
                shown.setdefault("options", []).append(key.removeprefix("open_conversation_"))
            return False

        def text_input(self, label, value, **kwargs):
            return "" if kwargs.get("key") == "conversation_search" else value

        def caption(self, *args, **kwargs):
            pass

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())

    selected = render_conversation_sidebar(store, "workspace-current", current.conversation_id)

    assert set(shown["options"]) == {current.conversation_id, historical.conversation_id}
    assert selected == current.conversation_id


def test_sidebar_unarchives_cross_session_conversation_using_its_session_id(tmp_path, monkeypatch):
    import sys

    from ui.conversations import render_conversation_sidebar

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    current = store.create("workspace-current", title="Current workspace")
    historical = store.create("workspace-old", title="Archived old conversation")
    store.archive("workspace-old", historical.conversation_id)
    actions = {"open_archived": True, "unarchive": False}

    class FakeStreamlit:
        def markdown(self, *args, **kwargs):
            pass

        def caption(self, *args, **kwargs):
            pass

        def button(self, label, **kwargs):
            if kwargs.get("key") == f"open_conversation_{historical.conversation_id}" and actions["open_archived"]:
                actions["open_archived"] = False
                return True
            return label == "取消归档" and actions["unarchive"]

        def text_input(self, label, value="", **kwargs):
            return "" if kwargs.get("key") == "conversation_search" else value

        def rerun(self):
            pass

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())

    selected = render_conversation_sidebar(store, "workspace-current", current.conversation_id)
    assert selected == historical.conversation_id
    actions["unarchive"] = True
    render_conversation_sidebar(store, "workspace-current", historical.conversation_id)

    assert store.get("workspace-old", historical.conversation_id).status == "active"


def test_sidebar_archives_current_cross_session_conversation_with_original_session_id(tmp_path, monkeypatch):
    import sys

    from ui.conversations import render_conversation_sidebar

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    current = store.create("workspace-old", title="Current old-workspace conversation")

    class FakeStreamlit:
        def markdown(self, *args, **kwargs):
            pass

        def text_input(self, label, value, **kwargs):
            return "" if kwargs.get("key") == "conversation_search" else value

        def caption(self, *args, **kwargs):
            pass

        def button(self, label, **kwargs):
            return label == "归档当前会话"

        def rerun(self):
            pass

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())

    render_conversation_sidebar(store, "workspace-current", current.conversation_id)

    assert store.get("workspace-old", current.conversation_id).status == "archived"


def test_sidebar_shows_searchable_conversation_navigation(tmp_path, monkeypatch):
    import sys

    from ui.conversations import render_conversation_sidebar

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    store.create("workspace-current", title="当前销售情况")
    historical = store.create("workspace-old", title="利润趋势复盘")
    store.create("workspace-old", title="区域销售拆分")
    calls = []

    class FakeStreamlit:
        def markdown(self, content, **kwargs):
            calls.append(("markdown", content))

        def text_input(self, label, **kwargs):
            calls.append(("text_input", label, kwargs.get("key")))
            return "利润" if kwargs.get("key") == "conversation_search" else ""

        def button(self, label, **kwargs):
            calls.append(("button", label, kwargs.get("key"), kwargs.get("icon")))
            return kwargs.get("key") == f"open_conversation_{historical.conversation_id}"

        def expander(self, *args, **kwargs):
            from contextlib import nullcontext

            return nullcontext()

        def caption(self, *args, **kwargs):
            pass

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())

    selected = render_conversation_sidebar(store, "workspace-current", None)

    search_call = ("text_input", "搜索会话", "conversation_search")
    visible_titles = [call[1] for call in calls if call[0] == "button"]
    assert search_call in calls
    new_conversation_button = next(call for call in calls if call[0] == "button" and call[2] == "new_conversation")
    assert new_conversation_button[3] is None
    assert "利润趋势复盘" in visible_titles
    assert "区域销售拆分" not in visible_titles
    assert selected == historical.conversation_id
