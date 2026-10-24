from datetime import date
from decimal import Decimal

from models.analysis import AnalysisRequest, AnalysisResult, Evidence, MetricValue
from models.report import NarrativeResult
from models.sales import DateRange
from reports.narrative import generate_narrative, validate_narrative


PERIOD = DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))


def _result(*, with_profit: bool = True) -> AnalysisResult:
    metrics = {
        "sales": MetricValue(value=Decimal("12345.67"), unit="USD"),
        "gross_profit": MetricValue(value=Decimal("3456.78"), unit="USD") if with_profit else MetricValue(value=None, unit="USD", reason="缺少成本字段，无法计算毛利"),
    }
    return AnalysisResult(
        analysis_id="analysis_narrative",
        dataset_id="dataset_narrative",
        request=AnalysisRequest(dataset_id="dataset_narrative", current_start=PERIOD.start, current_end=PERIOD.end, comparison="none", group_by=[]),
        metrics=metrics,
        evidence=[
            Evidence(evidence_id="ev_sales", kind="metric", label="销售额", value=Decimal("12345.67"), unit="USD", period=PERIOD),
            Evidence(evidence_id="ev_profit", kind="metric", label="毛利", value=Decimal("3456.78"), unit="USD", period=PERIOD),
        ],
    )


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.inputs = []

    def invoke(self, value):
        self.calls += 1
        self.inputs.append(value)
        response = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def _narrative(**kwargs):
    return NarrativeResult(
        summary=kwargs.get("summary", "销售额表现稳定。"),
        observations=kwargs.get("observations", [{"text": "销售额为 12345.67 USD。", "evidence_ids": ["ev_sales"]}]),
        recommendations=kwargs.get("recommendations", [{"text": "继续关注销售额表现。", "evidence_ids": ["ev_sales"]}]),
        hypotheses=kwargs.get("hypotheses", []),
        status="generated",
    )


def test_generate_narrative_accepts_valid_evidence_and_returns_structured_result():
    model = FakeModel([_narrative(hypotheses=["需要验证区域差异。"] )])

    narrative = generate_narrative(_result(), model)

    assert narrative.status == "generated"
    assert narrative.observations[0].evidence_ids == ["ev_sales"]
    assert narrative.recommendations[0].evidence_ids == ["ev_sales"]
    assert narrative.hypotheses == ["需要验证区域差异。"]
    assert model.calls == 1


def test_generate_narrative_retries_once_then_falls_back_for_fabricated_evidence():
    invalid = _narrative(observations=[{"text": "异常来自虚构来源。", "evidence_ids": ["ev_fake"]}])
    model = FakeModel([invalid, invalid])

    narrative = generate_narrative(_result(), model)

    assert narrative.status == "fallback"
    assert model.calls == 2
    assert all("ev_fake" not in item.evidence_ids for item in narrative.observations)
    assert "12345.67" in narrative.summary


def test_validate_narrative_rejects_unanchored_numbers_and_unavailable_profit_claims():
    narrative = _narrative(
        observations=[{"text": "销售额增长到 99999.00 USD。", "evidence_ids": ["ev_sales"]}],
        recommendations=[{"text": "毛利为 3000 USD，建议扩大投放。", "evidence_ids": ["ev_profit"]}],
    )

    errors = validate_narrative(narrative, _result(with_profit=False).evidence)

    assert errors
    assert any("number" in error.lower() or "数字" in error for error in errors)


def test_generate_narrative_falls_back_when_model_is_unavailable():
    model = FakeModel([RuntimeError("model unavailable")])

    narrative = generate_narrative(_result(), model)

    assert narrative.status == "fallback"
    assert model.calls == 2
    assert "12345.67" in narrative.summary
    assert any("3456.78" in item.text for item in narrative.observations)
    assert "model unavailable" in narrative.diagnostic


def test_validate_narrative_requires_recommendation_evidence_and_allows_hypotheses_without_evidence():
    narrative = _narrative(
        recommendations=[{"text": "建议检查区域结构。", "evidence_ids": []}],
        hypotheses=["待验证：区域差异是否由促销造成。"],
    )

    errors = validate_narrative(narrative, _result().evidence)

    assert errors
    assert any("recommend" in error.lower() or "建议" in error for error in errors)
from datetime import date


def test_create_narrative_model_requires_deepseek_api_key(monkeypatch):
    from agent.agent_setup import create_narrative_model

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert create_narrative_model() is None


def test_create_narrative_model_uses_deepseek_flash(monkeypatch):
    import agent.agent_setup as setup

    captured = {}

    class FakeModel:
        def with_structured_output(self, schema, **kwargs):
            captured["schema"] = schema
            return "structured-model"

    def fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return FakeModel()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(setup, "ChatOpenAI", fake_chat_openai)

    model = setup.create_narrative_model()

    assert model == "structured-model"
    assert captured["model"] == "deepseek-flash"
    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://api.deepseek.com"


def test_app_main_does_not_use_legacy_manual_analysis_controls():
    import app
    import inspect

    assert "render_analysis_controls(" not in inspect.getsource(app.main)

def test_create_narrative_model_uses_deepseek_json_mode(monkeypatch):
    import agent.agent_setup as setup

    captured = {}

    class FakeModel:
        def with_structured_output(self, schema, **kwargs):
            captured["schema"] = schema
            captured["kwargs"] = kwargs
            return "structured-model"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(setup, "ChatOpenAI", lambda **kwargs: FakeModel())

    assert setup.create_narrative_model() == "structured-model"
    assert captured["kwargs"] == {"method": "json_mode"}

def test_payload_explicitly_requests_json_output():
    from reports.narrative import _payload

    payload = _payload(_result())

    assert "JSON" in payload["instruction"]
    assert "summary" in payload["instruction"]


def test_model_receives_json_instruction_and_data_payload():
    model = FakeModel([_narrative()])

    generate_narrative(_result(), model)

    assert '"instruction"' in model.inputs[0]
    assert '"metrics"' in model.inputs[0]


def test_narrative_failure_diagnostic_redacts_api_key():
    model = FakeModel([RuntimeError("request failed with key sk-secret-value")])

    narrative = generate_narrative(_result(), model)

    assert narrative.status == "fallback"
    assert "request failed" in narrative.diagnostic
    assert "sk-secret-value" not in narrative.diagnostic


def test_narrative_logs_attempts_and_outcome_without_prompt_or_response(caplog):
    import logging

    model = FakeModel([_narrative(summary="PRIVATE_MODEL_RESPONSE")])
    logger = logging.getLogger("salespilot.reports.narrative")
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.INFO)
    try:
        narrative = generate_narrative(_result(), model)
        messages = " ".join(record.getMessage() for record in caplog.records)
    finally:
        logger.removeHandler(caplog.handler)
    assert narrative.status == "generated"
    assert "narrative.attempt.started" in messages
    assert "narrative.generation.completed" in messages
    assert "PRIVATE_MODEL_RESPONSE" not in messages
    assert '"instruction"' not in messages
