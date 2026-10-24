"""受控销售分析工具：只接受服务端 ID 和结构化请求。"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from analytics.analysis_service import AnalysisServiceError, run_analysis
from agent.context import require_runtime_context
from models.analysis import AnalysisRequest, AnalysisResult
from models.sales import ImportOptions
from data_sources.import_service import SourceSelection, build_source_preview
from storage.analyses import AnalysisStore
from storage.artifacts import ArtifactStore
from storage.datasets import DatasetStore, UnauthorizedDatasetError
from storage.profiles import load_dataset_profile
from storage.uploads import UploadStore
from workflow.business_report import run_business_report


_ALLOWED_FORMATS = {"word", "pdf"}


def _error(category: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"category": category, "message": message}}


def _context():
    try:
        return require_runtime_context()
    except RuntimeError as exc:
        return _error("missing_context", str(exc))


def _parse_request(request_json: str, dataset_id: str) -> AnalysisRequest | dict[str, Any]:
    try:
        if not isinstance(request_json, str):
            return _error("invalid_request", "request_json must be a JSON object string")
        payload = json.loads(request_json)
        if not isinstance(payload, dict):
            return _error("invalid_request", "request_json must decode to an object")
        forbidden = {"path", "sql", "python", "code", "exec", "query"}
        if forbidden.intersection(payload):
            return _error("invalid_request", "arbitrary path, SQL, or code is not accepted")
        payload["dataset_id"] = dataset_id
        return AnalysisRequest.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return _error("invalid_request", str(exc))


def create_analysis_tools(
    *,
    dataset_store: DatasetStore | None = None,
    upload_store: UploadStore | None = None,
    analysis_root: Path | str = ".runtime/analyses",
    artifact_root: Path | str = ".runtime/artifacts",
    report_root: Path | str = ".runtime/reports",
    include_import_tools: bool = False,
) -> list[Any]:
    """Build the three session-aware tools used by the new Agent."""

    dataset_store = dataset_store or DatasetStore()
    upload_store = upload_store or UploadStore()
    analysis_store = AnalysisStore(analysis_root)
    artifact_store = ArtifactStore(artifact_root)

    @tool
    def inspect_dataset(dataset_id: str) -> dict[str, Any]:
        """Inspect a dataset owned by the current session using its server-side dataset_id."""
        context = _context()
        if isinstance(context, dict):
            return context
        try:
            frame = dataset_store.load(context.session_id, dataset_id)
            profile = load_dataset_profile(dataset_store, context.session_id, dataset_id)
            return {
                "ok": True,
                "dataset_id": dataset_id,
                "rows": int(len(frame)),
                "columns": list(profile.columns),
                "min_date": profile.min_date.isoformat() if profile.min_date else None,
                "max_date": profile.max_date.isoformat() if profile.max_date else None,
                "grain": profile.grain,
                "currency": profile.currency,
                "available_metrics": profile.available_metrics,
                "unavailable_metrics": profile.unavailable_metrics,
            }
        except (UnauthorizedDatasetError, PermissionError, ValueError) as exc:
            return _error("unauthorized_dataset", str(exc))

    @tool
    def run_sales_analysis(dataset_id: str, request_json: str) -> dict[str, Any]:
        """Run deterministic sales analysis for a server-side dataset_id and controlled JSON options."""
        context = _context()
        if isinstance(context, dict):
            return context
        request = _parse_request(request_json, dataset_id)
        if isinstance(request, dict):
            return request
        try:
            frame = dataset_store.load(context.session_id, dataset_id)
            profile = load_dataset_profile(dataset_store, context.session_id, dataset_id)
            analysis = run_analysis(frame, request, profile)
            analysis_store.save(context.session_id, analysis.analysis_id, analysis)
            return {
                "ok": True,
                "analysis_id": analysis.analysis_id,
                "dataset_id": analysis.dataset_id,
                "request": analysis.request.model_dump(mode="json"),
                "metrics": {name: metric.model_dump(mode="json") for name, metric in analysis.metrics.items()},
                "comparisons": [item.model_dump(mode="json") for item in analysis.comparisons],
                "rankings": [item.model_dump(mode="json") for item in analysis.rankings],
                "anomalies": [item.model_dump(mode="json") for item in analysis.anomalies],
                "evidence": [item.model_dump(mode="json") for item in analysis.evidence],
            }
        except UnauthorizedDatasetError as exc:
            return _error("unauthorized_dataset", str(exc))
        except AnalysisServiceError as exc:
            return _error(exc.code, exc.message)
        except Exception as exc:
            return _error("analysis_failed", str(exc))

    @tool
    def export_business_report(analysis_id: str, format: str) -> dict[str, Any]:
        """Export a stored analysis as Word or PDF; format must be word or pdf."""
        context = _context()
        if isinstance(context, dict):
            return context
        if format not in _ALLOWED_FORMATS:
            return _error("invalid_format", "format must be word or pdf")
        try:
            payload = analysis_store.get(context.session_id, analysis_id)
            stored_analysis = AnalysisResult.model_validate(payload)
            request = stored_analysis.request
            workflow_result = run_business_report(
                context.session_id,
                request,
                [format],
                dataset_store=dataset_store,
                analysis_store=analysis_store,
                artifact_store=artifact_store,
                output_root=report_root,
                existing_analysis=stored_analysis,
            )
            if workflow_result.artifacts:
                return {
                    "ok": True,
                    "analysis_id": workflow_result.analysis_id,
                    "artifacts": [item.model_dump(mode="json") for item in workflow_result.artifacts],
                    "stage_status": workflow_result.stage_status,
                }
            return _error("export_failed", "; ".join(workflow_result.errors) or "export failed")
        except PermissionError as exc:
            return _error("unauthorized_analysis", str(exc))
        except (TypeError, ValueError, KeyError) as exc:
            return _error("invalid_analysis", str(exc))
        except Exception as exc:
            return _error("export_failed", str(exc))

    @tool
    def inspect_import_source(source_id: str) -> dict[str, Any]:
        """Inspect a current-session uploaded source using its server-side source_id."""
        context = _context()
        if isinstance(context, dict):
            return context
        try:
            selection = upload_store.resolve(context.session_id, source_id)
            options = ImportOptions(
                source_name=Path(selection.path).name,
                grain="order" if selection.kind == "sqlite" else "aggregate",
                currency=None,
            )
            preview = build_source_preview(selection, options)
            return {
                "ok": True,
                "source_id": source_id,
                "source_columns": list(preview.source_columns),
                "suggested_mapping": preview.mapping.mapping,
                "sample_rows": preview.frame.head(3).astype(object).where(
                    preview.frame.head(3).notna(), None
                ).to_dict(orient="records"),
                "validation_valid": preview.validation.valid,
                "issues": [
                    issue.model_dump(mode="json") for issue in preview.validation.errors[:20]
                ],
            }
        except PermissionError as exc:
            return _error("unauthorized_source", str(exc))
        except (ValueError, FileNotFoundError) as exc:
            return _error("invalid_source", str(exc))
        except Exception as exc:
            return _error("source_inspection_failed", str(exc))

    @tool
    def validate_and_save_dataset(
        source_id: str,
        mapping_json: str,
        options_json: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Validate a proposed column mapping and persist only valid session-owned uploads."""
        context = _context()
        if isinstance(context, dict):
            return context
        try:
            selection = upload_store.resolve(context.session_id, source_id)
            if not idempotency_key or len(idempotency_key) > 200:
                return _error("invalid_request", "idempotency_key is required and must be short")
            mapping = json.loads(mapping_json)
            options_payload = json.loads(options_json)
            if not isinstance(mapping, dict) or not isinstance(options_payload, dict):
                return _error("invalid_request", "mapping_json and options_json must encode objects")
            options_payload["source_name"] = Path(selection.path).name
            options = ImportOptions.model_validate(options_payload)
            preview = build_source_preview(selection, options, mapping=mapping)
            if not preview.validation.valid or preview.profile is None:
                return {
                    "ok": False,
                    "status": "validation_failed",
                    "error": {
                        "category": "validation_failed",
                        "message": "source data did not pass deterministic validation",
                    },
                    "issues": [issue.model_dump(mode="json") for issue in preview.validation.errors[:50]],
                    "warnings": [issue.model_dump(mode="json") for issue in preview.validation.warnings[:20]],
                }
            fingerprint_payload = json.dumps(
                {
                    "source_id": source_id,
                    "mapping": mapping,
                    "options": options.model_dump(mode="json"),
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            request_fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()
            profile = preview.validation.profile.model_copy(
                update={"session_id": context.session_id}
            )
            reference = dataset_store.save_idempotent(
                context.session_id,
                preview.frame,
                profile,
                idempotency_key=f"import:{source_id}:{request_fingerprint}",
                request_fingerprint=request_fingerprint,
            )
            profile = load_dataset_profile(dataset_store, context.session_id, reference.dataset_id)
            return {
                "ok": True,
                "status": "dataset_saved",
                "dataset_id": reference.dataset_id,
                "rows": profile.rows,
                "columns": profile.columns,
                "grain": profile.grain,
                "currency": profile.currency,
                "available_metrics": profile.available_metrics,
                "unavailable_metrics": profile.unavailable_metrics,
            }
        except PermissionError as exc:
            return _error("unauthorized_source", str(exc))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return _error("invalid_import", str(exc))
        except Exception as exc:
            return _error("import_failed", str(exc))

    @tool
    def inspect_analysis_result(analysis_id: str) -> dict[str, Any]:
        """Load a persisted analysis and its deterministic evidence for this session."""
        context = _context()
        if isinstance(context, dict):
            return context
        try:
            stored = AnalysisResult.model_validate(
                analysis_store.get(context.session_id, analysis_id)
            )
            return {
                "ok": True,
                "analysis_id": stored.analysis_id,
                "dataset_id": stored.dataset_id,
                "request": stored.request.model_dump(mode="json"),
                "metrics": {
                    name: metric.model_dump(mode="json")
                    for name, metric in stored.metrics.items()
                },
                "comparisons": [item.model_dump(mode="json") for item in stored.comparisons],
                "rankings": [item.model_dump(mode="json") for item in stored.rankings],
                "anomalies": [item.model_dump(mode="json") for item in stored.anomalies],
                "evidence": [item.model_dump(mode="json") for item in stored.evidence],
            }
        except PermissionError as exc:
            return _error("unauthorized_analysis", str(exc))
        except (TypeError, ValueError, KeyError) as exc:
            return _error("invalid_analysis", str(exc))

    tools = [inspect_dataset, run_sales_analysis, export_business_report]
    if include_import_tools:
        tools.extend([inspect_import_source, validate_and_save_dataset, inspect_analysis_result])
    return tools
