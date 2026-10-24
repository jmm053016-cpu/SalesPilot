from ui.theme import build_stage_statuses, source_option_cards, theme_css
from ui.workbench import sample_csv_template


def test_source_option_cards_expose_file_type_identity():
    cards = source_option_cards()
    assert [card["value"] for card in cards] == ["CSV", "Excel", "SQLite"]
    assert all(card["extension"] for card in cards)
    assert all(card["icon_svg"].startswith("<svg") for card in cards)


def test_sample_csv_template_has_required_business_columns():
    template = sample_csv_template()
    assert "order_date" in template
    assert "sales_amount" in template
    assert template.count("\n") >= 2


def test_theme_css_contains_upload_states_and_sidebar_contrast():
    css = theme_css()
    assert ".cb-upload" in css
    assert ".cb-upload.is-success" in css
    assert ".cb-upload.is-error" in css
    assert "!important" in css
    assert "--cb-space-6" in css
    assert ".cb-template-link" in css
    assert ".cb-upload-icon" in css
    assert "div.stDownloadButton > button" in css
    assert "border-radius: 14px" not in css
    assert "[data-testid=\"stFileUploader\"]" in css
    assert ".cb-upload-empty" in css


def test_stage_statuses_keep_current_done_pending_distinct():
    assert {status for _, status in build_stage_statuses(dataset_id=None, analysis_id=None)} == {
        "active", "pending"
    }
    assert {status for _, status in build_stage_statuses(dataset_id="ds", analysis_id="an")} == {
        "done", "active", "pending"
    }
