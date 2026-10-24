from pathlib import Path
import inspect


def test_initialize_conversation_state_creates_before_sidebar_render(tmp_path):
    from app import initialize_conversation_state
    from storage.conversations import ConversationStore

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    state = {
        "analysis_session": __import__("ui.session", fromlist=["create_analysis_session"]).create_analysis_session("session-a"),
        "conversation_initialized": False,
        "followup_messages": [],
        "followup_events": [],
    }

    initialize_conversation_state(store, state)

    assert state["conversation_initialized"] is True
    session = state["analysis_session"]
    assert session.conversation_id
    assert store.list_history("session-a")


def test_main_does_not_render_manual_analysis_controls():
    import app

    source = inspect.getsource(app.main)

    assert "render_analysis_controls(" not in source
    assert "wb_reconfigure_analysis" not in source


def test_followup_is_only_available_after_analysis_result_exists():
    from app import can_render_followup

    assert can_render_followup(agent=object(), result=object()) is True
    assert can_render_followup(agent=object(), result=None) is False
    assert can_render_followup(agent=None, result=object()) is False
