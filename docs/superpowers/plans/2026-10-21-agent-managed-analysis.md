# Agent 驱动的数据导入与分析实施计划

> **实施约束：**按任务顺序执行，每项先添加失败测试再实现。保留现有手动工作台作为模型不可用、映射不确定或校验失败时的回退路径。不要清理或覆盖工作区中的既有修改；提交时只暂存本计划明确列出的文件。

**目标：**让用户提供文件并用自然语言描述分析目标后，Agent 能通过受控工具完成字段映射、确定性校验、数据集保存、确定性分析，并基于持久化分析结果继续讨论。

**架构：**将导入预览、映射校验与保存从 `ui/data_entry.py` 的 UI 依赖中抽成可复用服务；Agent 工具只接收会话内服务端源 ID、结构化映射和分析参数。模型不处理完整 DataFrame，不计算指标；所有写入继续通过 session-aware stores。Streamlit 工作台提供上传、Agent 进度及需确认状态，并保留传统手动映射/分析入口。

**技术栈：**Python、Pydantic v2、Pandas、LangChain tools、Streamlit、现有 DatasetStore/AnalysisStore/ConversationStore 和 pytest。

## 文件与职责

- `data_sources/import_service.py`（新增）：纯服务层的 source preview、mapping validation、dataset save 组合 API；复用现有 reader、mapper、validator、DatasetStore。
- `ui/data_entry.py`：保留已有公开函数作为兼容封装，调用共享服务，避免 UI 与 Agent 规则分叉。
- `models/sales.py`：只在测试证明需要时新增结构化导入选项/结果模型；优先复用现有 `ColumnMapping`、`ImportOptions`、`ValidationResult`。
- `storage/uploads.py`（新增）：会话隔离的上传源暂存与服务端 source ID 解析；禁止模型传入文件路径。
- `agent/analysis_tools.py`：增加受控源画像、验证保存、分析结果读取/追问所需工具；沿用运行时上下文和结构化错误。
- `agent/prompts.py`：约束 Agent 的导入、澄清、分析及证据引用行为。
- `agent/agent_setup.py`：注入完整工具集合，维持工具预算、超时和兼容运行时。
- `ui/workbench.py`、`ui/followup.py`、`app.py`：接通上传到 Agent 的工作流、阶段状态与恢复后的分析引用；手动路径保留。
- `tests/test_import_service.py`、`tests/test_upload_store.py`、`tests/test_analysis_tools.py`、`tests/test_ui_workbench.py`、新增端到端测试：覆盖服务规则、授权、状态流转和既有兼容行为。

## 任务 1：抽取可复用导入服务

**文件：**新增 `tests/test_import_service.py`；新增 `data_sources/import_service.py`；修改 `ui/data_entry.py`。

1. 添加测试 `test_preview_uses_shared_reader_mapping_and_validator`：CSV、Excel、allowlisted SQLite 预览通过同一 API 返回 `SourcePreview`，列映射和现有 validator 结果与当前 UI 函数一致。
2. 添加测试 `test_invalid_mapping_and_invalid_data_never_persist`：未知源列、重复目标字段、缺少必需字段及非法日期均不得调用 store.save。
3. 添加测试 `test_valid_preview_persists_session_owned_dataset`：有效预览保存后 DatasetRef 属于调用 session，数据可由 DatasetStore 加载。
4. 在 `data_sources/import_service.py` 实现 `build_source_preview(selection: SourceSelection, options: ImportOptions, mapping: dict[str, str] | None = None) -> SourcePreview` 与 `persist_preview(session_id: str, preview: SourcePreview, dataset_store: DatasetStore) -> DatasetRef`；将实现从 UI 文件移入服务层。
5. 将 `ui/data_entry.py` 的同名 API 改为兼容转发或显式重导出；当前调用方与既有 `tests/test_ui_data_entry.py` 必须保持通过。
6. 运行 `uv run pytest tests/test_import_service.py tests/test_ui_data_entry.py -q`，全部通过。

## 任务 2：增加会话隔离的上传源引用

**文件：**新增 `tests/test_upload_store.py`；新增 `storage/uploads.py`；修改 `ui/workbench.py` 的上传入口。

1. 添加 `test_upload_source_is_retrievable_only_by_owner_session`：源 ID 不能跨 session 读取；模型传入路径、`..` 或未知 ID 不会逃逸存储根目录。
2. 添加 `test_upload_source_has_size_and_extension_limits`：超出配置上限、非允许格式及空文件均返回分类错误，不落盘。
3. 添加 `test_same_upload_id_is_idempotent`：同一 session/source key 重试返回同一引用，不重复创建源文件。
4. 实现 `UploadStore(root, max_bytes, allowed_suffixes)`，方法 `save(session_id, filename, content, source_key) -> SourceRef`、`resolve(session_id, source_id) -> SourceSelection`；SourceRef 只公开 ID、文件名、格式和大小，不向 Agent 暴露绝对路径。
5. 现有 Streamlit uploader 将上传内容存入 UploadStore；原有手工预览流程继续能从服务端 SourceRef 解析源数据。
6. 运行 `uv run pytest tests/test_upload_store.py tests/test_ui_data_entry.py -q`，全部通过。

## 任务 3：Agent 自动映射、校验和保存

**文件：**新增 `tests/test_import_tools.py`；修改 `agent/analysis_tools.py`、`agent/prompts.py`、`agent/agent_setup.py`。

1. 添加 `test_inspect_import_source_returns_bounded_preview_without_path`：只返回有限行样例、列名、类型/空值概况，不包含绝对路径；未授权源返回 `unauthorized_source`。
2. 添加 `test_mapping_rejects_unknown_duplicate_and_missing_required_fields`：映射列必须存在、标准目标不可重复，`order_date` 和 `sales_amount` 缺失时不得保存。
3. 添加 `test_validate_and_save_tool_persists_only_valid_data`：有效输入生成 session-owned dataset；非法输入状态为 `validation_failed` 且 dataset store 为空。
4. 添加 `test_low_confidence_mapping_requests_user_input`：仅精确标准名/配置 alias 命中且必需字段完整时自动通过；其他未知/冲突列返回 `needs_user_input` 和候选字段，不信任模型自报置信分数。
5. 增加 `inspect_import_source(source_id)`、`validate_and_save_dataset(source_id, mapping, import_options, idempotency_key)` 受控工具；工具使用 `require_runtime_context()` 解析当前 session，调用 `UploadStore` 和任务 1 的共享服务。对重复 idempotency key 返回先前结果。
6. 更新系统提示：先检查源与映射，只有工具返回 saved 才进入分析；需要确认时向用户提问；数据内容中的指令不是系统指令；不得访问路径、SQL 或生成业务数值。
7. `create_agent()` 组合导入工具与现有分析/导出工具；更新工具预算相关测试以确保完整流程在预算内。
8. 运行 `uv run pytest tests/test_import_tools.py tests/test_analysis_tools.py tests/test_upload_store.py -q`，全部通过。

## 任务 4：自然语言规划并自动运行确定性分析

**文件：**新增 `tests/test_analysis_planning.py`；修改 `agent/analysis_tools.py`、`agent/prompts.py`、必要时修改 `models/analysis.py`。

1. 添加 `test_run_sales_analysis_validates_structured_request_and_uses_session_dataset`：请求必须通过 `AnalysisRequest`，dataset 授权基于运行时 session；非法日期/维度返回 `invalid_request`。
2. 添加 `test_analysis_tool_returns_persisted_evidence_and_id`：工具结果包含 analysis_id、结构化指标、comparisons、rankings、anomalies、evidence，并与 `AnalysisStore` 保存内容一致。
3. 添加 `test_analysis_request_must_not_invent_unavailable_dimensions`：请求的分组字段必须存在于画像列；模型无法从用户意图与画像确定开始/结束日期时返回 `needs_user_input`，确定时调用 run_analysis，不允许 Agent 生成指标值。
4. 给 Agent 增加结构化分析参数规划约束：日期范围、comparison、group_by 由 `AnalysisRequest` 验证；可推断默认值须明示；需要澄清的结果由 Agent 询问，不调用分析工具。
5. 保持指标计算唯一入口为 `analytics.analysis_service.run_analysis`；工具将完整结构化结果保存后仅返回必要摘要和 evidence。
6. 运行 `uv run pytest tests/test_analysis_planning.py tests/test_analysis_tools.py tests/test_report_workflow.py -q`，全部通过。

## 任务 5：接入工作台自动流程及异常修复入口

**文件：**新增 `tests/test_agent_managed_workflow.py`；修改 `ui/workbench.py`、`ui/followup.py`、`app.py`。

1. 添加 `test_uploaded_source_and_goal_start_agent_workflow`：上传源并提交分析目标后，UI 发起 Agent 调用，流式阶段包含 profiling/mapping/validation/analysis；不要求点击传统“保存数据集”或“运行分析”。
2. 添加 `test_needs_user_input_resumes_after_confirmation`：低置信映射呈现字段选择控件；确认后继续同一导入任务，不重复保存。
3. 添加 `test_model_unavailable_keeps_manual_workbench`：模型配置缺失时传统映射与确定性分析入口可继续使用。
4. 添加 `test_validation_failure_keeps_source_and_explains_issues`：原始上传源保留，UI 显示字段与行号错误，不创建 dataset/analysis。
5. 在工作台增加自动模式的目标输入、Agent 事件流与任务状态展示；调用既有 `stream_agent`，不把大文件写进 prompt。session state 仅保存 source_id、状态和资源引用。
6. 成功后通过现有会话/分析 session 绑定 dataset_id 与 analysis_id；失败不覆盖此前有效绑定。保持人工模式可达。
7. 运行 `uv run pytest tests/test_agent_managed_workflow.py tests/test_ui_workbench.py tests/test_ui_data_entry.py -q`，全部通过。

## 任务 6：分析后证据讨论与重启恢复

**文件：**新增/修改 `tests/test_followup_persistence.py`；修改 `agent/analysis_tools.py`、`agent/prompts.py`、`ui/followup.py`、`app.py`、`storage/conversations.py`（仅在需要新增资源引用 API 时）。

1. 添加 `test_followup_loads_analysis_by_session_owned_id`：Agent 追问前按 session 从 AnalysisStore 读取绑定的 AnalysisResult 和 DatasetProfile；伪造或跨 session analysis_id 被拒绝。
2. 添加 `test_followup_numeric_answers_require_analysis_evidence`：系统 prompt 与工具上下文提供的证据摘要支持回答已计算指标；对未计算维度必须重新调用分析工具或明确说信息不足。
3. 添加 `test_conversation_restores_dataset_and_analysis_references_after_restart`：重新创建 app stores 后，从持久化 conversation 还原资源引用；缺失资源返回明确错误，不生成无依据回答。
4. 若 ConversationStore 尚无原子资源绑定 API，增加 `bind_analysis_resources(session_id, conversation_id, dataset_id, analysis_id, report_ids)`；所有引用先通过对应 store 验权，再写入会话记录。
5. 追问调用携带当前已完成 analysis_id；新分析成功时更新对话资源绑定。消息仍只保存文本和轻量 metadata，不保存 DataFrame 或整个分析对象。
6. 运行 `uv run pytest tests/test_followup_persistence.py tests/test_conversation_store.py tests/test_conversation_lifecycle.py -q`，全部通过。

## 任务 7：端到端与回归验证

**文件：**新增 `tests/test_agent_managed_workflow.py` 的集成场景；不新增无关依赖。

1. 完整集成测试以小型 CSV 和 fake structured-output model 驱动上传、映射、保存、分析、追问；断言最终数值等于直接调用 `run_analysis` 的结果，且分析 evidence 被传入讨论上下文。
2. 增加失败集成测试：歧义字段暂停、非法数据不保存、模型超时保持可重试、跨会话资源拒绝、重复导入幂等。
3. 运行全量测试：`uv run pytest -q`，目标为全部通过；记录当前基线已有的模型配置优先级失败，并通过隔离环境变量或修复对应行为保证最终回归可重复。
4. 运行语法与差异检查：`uv run python -c "import pathlib, py_compile; files=[p for p in pathlib.Path('.').rglob('*.py') if 'tests' not in p.parts and '.venv' not in p.parts]; [py_compile.compile(str(p), doraise=True) for p in files]; print(f'compiled {len(files)} source files')"` 及 `git diff --check`。
5. 检查 `git status --short`，只审阅本计划产生的差异；不得覆盖本工作开始前的工作区改动。

## 依赖关系

任务 1 → 任务 2 → 任务 3 → 任务 4 → 任务 5 → 任务 6 → 任务 7。任务 3、4 的底层接口先稳定，再接 UI，避免 UI 同时承担 Agent 逻辑与导入业务规则。

## 审查重点

- Agent 能否把上传内容中的恶意指令当作普通数据，而非工具策略。
- 映射检查是否同时拒绝重复标准字段、缺必需列及不可信 source_id。
- 重试/Streamlit rerun 是否造成多个 dataset 或重复分析任务。
- 多会话访问是否在每个 store 读取入口都拒绝，而不只在 UI 隐藏资源。
- 追问恢复是否只使用持久化分析结果，不能依赖进程内 LangGraph 短期 checkpoint 才正确。
