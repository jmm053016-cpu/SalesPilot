from ui.theme import theme_css


def test_sidebar_overrides_streamlit_code_and_status_colors():
    css = theme_css()

    assert '[data-testid="stSidebar"] code' in css
    assert 'color: #17211f !important' in css
    assert '[data-testid="stSidebar"] .cb-status' in css
    assert '[data-testid="stSidebar"] button' in css
    assert 'color: #f5f3ee !important' in css
    assert ".cb-sidebar-brand" in css
    assert ".cb-sidebar-section-title" in css
    assert ".cb-sidebar-workspace" in css
    assert ".cb-sidebar-footer" in css
    assert "stBaseButton-primary" in css


def test_sidebar_actions_do_not_pass_material_icon_tokens():
    css = theme_css()
    from pathlib import Path

    source = Path("app.py").read_text(encoding="utf-8")
    assert ":material/" not in source
    assert ":material/" not in css
