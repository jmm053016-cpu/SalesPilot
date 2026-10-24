from ui.theme import build_stage_statuses, theme_css


def test_theme_css_contains_workbench_visual_tokens():
    css = theme_css()

    assert "--cb-ink" in css
    assert "--cb-accent" in css
    assert ".cb-hero" in css
    assert ".cb-stage" in css
    assert "border-radius: 14px" not in css
    assert "border-radius: 8px" in css
    assert ".cb-stage-connector" in css
    assert "text-decoration: underline" in css
    assert "letter-spacing: -" not in css
    assert "font-size: clamp(2.5rem, 5vw, 5.2rem)" not in css


def test_stage_statuses_reflect_session_progress():
    assert build_stage_statuses(dataset_id=None, analysis_id=None) == [
        ("数据源", "active"),
        ("字段校验", "pending"),
        ("分析配置", "pending"),
        ("结果洞察", "pending"),
        ("报告导出", "pending"),
    ]
    assert build_stage_statuses(dataset_id="ds_1", analysis_id=None)[0:3] == [
        ("数据源", "done"),
        ("字段校验", "done"),
        ("分析配置", "active"),
    ]
    assert build_stage_statuses(dataset_id="ds_1", analysis_id="an_1")[2:] == [
        ("分析配置", "done"),
        ("结果洞察", "active"),
        ("报告导出", "pending"),
    ]
