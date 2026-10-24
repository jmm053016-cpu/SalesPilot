"""根据确定性分析证据生成结构化解读，并提供失败回退内容。"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from time import perf_counter
from typing import Any

from models.analysis import AnalysisResult, Evidence
from models.report import NarrativeResult, Observation, Recommendation
from utils.logging_config import get_logger

logger = get_logger(__name__)

_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")
_SECRET_RE = re.compile(r"(?i)(?:sk-[a-z0-9_-]{8,}|(?:api[_ -]?key|authorization)\s*[:=]?\s*\S+)")


def _metric_text(result: AnalysisResult, name: str) -> str:
    metric = result.metrics.get(name)
    if metric is None:
        return "不可用"
    if metric.value is None:
        return metric.reason or "不可用"
    return f"{metric.value} {metric.unit}"


def _fallback(result: AnalysisResult, diagnostic: str | None = None) -> NarrativeResult:
    sales = _metric_text(result, "sales")
    observations = [Observation(text=f"销售额为 {sales}。", evidence_ids=[item.evidence_id for item in result.evidence if item.label in {"销售额", "sales"}])]
    profit = result.metrics.get("gross_profit")
    if profit is not None:
        if profit.value is None:
            observations.append(Observation(text=profit.reason or "毛利不可用。", evidence_ids=[]))
        else:
            observations.append(Observation(text=f"毛利为 {profit.value} {profit.unit}。", evidence_ids=[item.evidence_id for item in result.evidence if item.label in {"毛利", "gross_profit"}]))
    return NarrativeResult(
        summary=f"本期销售额为 {sales}，以下内容为基于确定性指标的事实摘要。",
        observations=observations,
        recommendations=[],
        hypotheses=[],
        status="fallback",
        diagnostic=diagnostic,
    )


def _payload(result: AnalysisResult) -> dict[str, Any]:
    return {
        "instruction": ("Return only valid JSON, with no Markdown fences. Follow this exact structure: "
            '"summary": string, "observations": [{"text": string, "evidence_ids": [evidence ID strings]}], '
            '"recommendations": [{"text": string, "evidence_ids": [evidence ID strings]}], '
            '"hypotheses": [string], "status": "generated". Do not use strings in place of observation or recommendation objects. '
            'Only cite evidence IDs provided in the input. Write the narrative in Chinese.'
            ' Use only numeric values explicitly present in evidence; do not calculate ratios or add dates.'
        ),
        "metrics": {name: {"value": str(metric.value) if metric.value is not None else None, "unit": metric.unit, "reason": metric.reason} for name, metric in result.metrics.items()},
        "evidence": [{"evidence_id": item.evidence_id, "kind": item.kind, "label": item.label, "value": str(item.value) if item.value is not None else None, "unit": item.unit, "period": item.period.model_dump(mode="json") if item.period else None} for item in result.evidence],
        "period": {"start": result.request.current_start.isoformat(), "end": result.request.current_end.isoformat()},
    }


def _coerce_response(response: Any) -> NarrativeResult:
    if isinstance(response, NarrativeResult):
        return response
    if hasattr(response, "content"):
        response = response.content
    if isinstance(response, str):
        try:
            return NarrativeResult.model_validate(json.loads(response))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("model response must be valid narrative JSON") from exc
    if isinstance(response, dict):
        return NarrativeResult.model_validate(response)
    raise ValueError("model response must be NarrativeResult or mapping")


def validate_narrative(narrative: NarrativeResult, evidence: list[Evidence]) -> list[str]:
    valid_ids = {item.evidence_id for item in evidence}
    evidence_values = {str(item.value) for item in evidence if item.value is not None}
    errors: list[str] = []
    for kind, items in (("observation", narrative.observations), ("recommendation", narrative.recommendations)):
        for item in items:
            if not item.evidence_ids:
                errors.append(f"{kind} must cite evidence")
            unknown = set(item.evidence_ids) - valid_ids
            if unknown:
                errors.append(f"{kind} cites unknown evidence: {sorted(unknown)}")
            for number in _NUMBER_RE.findall(item.text):
                normalized = number.lstrip("+")
                if normalized not in evidence_values:
                    try:
                        candidate = Decimal(normalized)
                        if not any(Decimal(value) == candidate for value in evidence_values):
                            errors.append(f"{kind} contains unsupported number: {number}")
                    except Exception:
                        errors.append(f"{kind} contains unsupported number: {number}")
    return errors


def generate_narrative(result: AnalysisResult, model: Any | None) -> NarrativeResult:
    if model is None:
        logger.warning(
            "narrative.generation.unavailable | 模型解读不可用 | 分析ID=%s | 模型=deepseek-flash | 处理方式=使用确定性事实摘要",
            result.analysis_id,
        )
        return _fallback(result, "Narrative model is not initialized; check DEEPSEEK_API_KEY and restart the app.")
    started = perf_counter()
    payload = _payload(result)
    last_error = "model returned invalid narrative"
    for attempt in range(2):
        logger.info(
            "narrative.attempt.started | 开始调用模型解读 | 分析ID=%s | 模型=deepseek-flash | 尝试次数=%d | 最大尝试次数=2",
            result.analysis_id,
            attempt + 1,
        )
        try:
            request_payload = dict(payload)
            if attempt:
                request_payload["instruction"] += " Fix these validation errors: " + last_error
            narrative = _coerce_response(model.invoke(json.dumps(request_payload, ensure_ascii=False)))
            errors = validate_narrative(narrative, result.evidence)
            if not errors:
                logger.info(
                    "narrative.generation.completed | 模型解读生成成功 | 分析ID=%s | 状态=generated | 尝试次数=%d | 观察数量=%d | 建议数量=%d | 耗时=%d毫秒",
                    result.analysis_id,
                    attempt + 1,
                    len(narrative.observations),
                    len(narrative.recommendations),
                    int((perf_counter() - started) * 1000),
                )
                return narrative
            last_error = "Narrative validation failed: " + "; ".join(errors)
            logger.warning("narrative.attempt.invalid | 模型解读校验未通过 | 分析ID=%s | 第%d次尝试 | 校验错误数=%d", result.analysis_id, attempt + 1, len(errors))
        except Exception as exc:
            last_error = _SECRET_RE.sub('[REDACTED]', str(exc))[:500]
            logger.warning("narrative.attempt.failed | 模型解读调用失败 | 分析ID=%s | 第%d次尝试 | 异常类型=%s", result.analysis_id, attempt + 1, type(exc).__name__)
    logger.warning("narrative.generation.fallback | 模型解读失败，已回退为确定性事实摘要 | 分析ID=%s | 尝试次数=2 | 耗时=%d毫秒", result.analysis_id, int((perf_counter() - started) * 1000))
    return _fallback(result, last_error)
