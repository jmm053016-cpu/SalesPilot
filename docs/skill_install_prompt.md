# SalesPilot 文档表格 Skill 安装提示词

> 用途：把本文件全文作为提示词投给任意 Agent（Claude Code / WorkBuddy / Cursor 等），
> 在 SalesPilot 项目中落地「excel-skill + anthropics document-skills」两条文档表格能力链。
> 自包含设计：执行环境的 Agent 看不到原始对话，本提示词已带齐全部目标、路径、依赖与验收标准。

---

## 提示词正文（复制以下全部内容）

```
【任务】在 SalesPilot 项目（D:/python/program/SalesPilot，Python 工程）中安装两套文档表格 Agent Skill，并验证可用。

【背景】
- 本项目技术栈：pandas==2.2.3、openpyxl>=3.1,<4、python-docx>=1.1,<2、pypdf>=5,<7（见 requirements.txt）。
- 项目实际处理四类文件：CSV 导入（data_sources/csv_source.py）、Excel 读写与公式（data_sources/excel_source.py、excel_formulas.py）、Word 报表（reports/word_report.py）、PDF 报表（reports/pdf_report.py）。
- 目标：让 Agent 具备 xlsx 生成 + lint + 销售行业模板能力，以及 docx/pdf 报表生成能力；不得引入与现有 pip 依赖冲突的新依赖。

【既有 skill 盘点与保护（最高优先级，先于任何安装动作）】
1. 安装前必须先枚举以下全部位置，列出现有 skill 清单（目录名 + SKILL.md 的 name 字段）：
   - 项目级：D:/python/program/SalesPilot/.workbuddy-ai/skills/、.claude/skills/、.agents/skills/、.cursor/
   - 用户级：C:/Users/林/.workbuddy-ai/skills/、~/.claude/skills/、~/.agents/skills/
   - 宿主内置/已启用 skill（如 WorkBuddy 内置的 workbuddy-sheet-generation、workbuddy-docx、workbuddy-local-office-edit、workbuddy-sheetagent 等），通过当前会话可用 skill 列表或 skill_management 工具获取。
2. 铁律：本次只允许【新增】本提示词指定的 skill，严禁删除、覆盖、重命名、移动任何既有 skill；既有 skill 的 SKILL.md、scripts/、references/ 一个字节都不许动。
3. 去重与冲突处理：
   - 目标 skill 名（excel-skill、docx、pdf、pptx、xlsx、convert-excel-to-md、convert-word-to-md、convert-pdf-to-md）与既有 skill 同名时，跳过安装该 skill 并在报告中说明「已存在，保留原版」；
   - 既有 skill 功能已覆盖目标能力时（如宿主已启用 workbuddy-sheet-generation/workbuddy-docx 且工作正常），只装缺口部分，不重复装；
   - 同名但确需用新版替换时，先把原目录备份为 <name>.bak-<日期>，再装新版，报告中写明备份路径。
4. 若项目/用户级 skill 目录不存在，创建之；不要修改目录以外的任何配置文件（如 settings.json、mcp.json）除非安装插件方式必需。

【安装目标 1：gaaiyun/excel-skill（主力）】
- 仓库：https://github.com/gaaiyun/excel-skill
- 安装方式：git clone 到临时目录，将 skill 目录复制到项目的 .claude/skills/excel-skill（若项目用通用 Agent Skills 规范，则放 .agents/skills/excel-skill，两个位置都放一份，保证 Claude Code 与通用宿主都能加载）。
- 要求完整复制：SKILL.md、references/、scripts/、templates/、tutorials/、examples/、README.md、WORKFLOW.md、INSTALL_CN.md。
- 安装后确认 SKILL.md frontmatter 的 name 为 excel-skill、description 完整（含 openpyxl/pandas 生成、公式、透视表、lint 触发条件）。

【安装目标 2：anthropics/skills document-skills（补 docx/pdf）】
- 仓库：https://github.com/anthropics/skills
- 安装方式（按优先级选可用的）：
  1. Claude Code：/plugin marketplace add anthropics/skills，然后 /plugin install document-skills@anthropic-agent-skills；
  2. 非 Claude Code 宿主：git clone 后从 skills/ 下取 docx、pdf、pptx、xlsx 四个目录，复制到 .agents/skills/（与 excel-skill 同级的 skills 目录）。
- 注意：该仓库文档四件套为 source-available（非 Apache 2.0），仅限本项目内部使用，不要把源码再分发到公开仓库。

【安装目标 3：转换链（可选增强）】
- 从 https://github.com/github/awesome-copilot 的 skills/ 下取 convert-excel-to-md、convert-word-to-md、convert-pdf-to-md 三个 skill，复制到同一 skills 目录，用于上传表格/文档先转 Markdown 再做分析的前处理。

【验证步骤（必须全部执行并汇报结果）】
0. 既有 skill 完好性：对比安装前枚举的清单，确认所有既有 skill 目录数量、文件数、SKILL.md name 均无变化（有 .bak 备份的除外）。
1. 依赖检查：pip install -r requirements.txt 在现有环境无新增冲突；确认 openpyxl、pandas、python-docx、pypdf 均可 import。
2. skill 可加载检查：确认 skills 目录下每个 SKILL.md 的 YAML frontmatter 合法（name + description 两个必需字段），无重复 name。
3. excel-skill 功能验证：
   a. 用 templates/ 下 FMCG 销售模板（销售达成 / RTM / SKU ABC）生成一个测试 xlsx 到项目 tests/ 临时目录；
   b. 对该文件运行 scripts/analyze.py 体检，确认无 XA001~XA010 类错误；
   c. 如生成代码含公式，确认已提示 LibreOffice 重算或 Excel 打开自动重算（openpyxl 公式为字符串、data_only=True 误用导致公式丢失这两个坑必须规避）。
4. document-skills 功能验证：用 docx skill 生成一份测试 Word 报表、用 pdf skill 生成一份测试 PDF，落到 tests/ 临时目录，确认文件可打开、非空。
5. 清理：删除验证产生的临时 xlsx/docx/pdf 与 clone 的临时仓库目录，保留 skills 安装结果。

【产出物】
1. 既有 skill 盘点清单（安装前全量枚举结果，标注哪些是保留项）。
2. skills 安装结果目录清单（.claude/skills/ 与 .agents/skills/ 各有什么，新增项与保留项分开列）。
3. 验证报告：每步通过/失败 + 失败时的报错原文与修复动作。
4. 若任何一步失败：给出等价替代路径继续推进，不要中途停止；最终明确说明哪条路径不可用及原因。

【验收标准】
- 两类 skill 在项目内可被 Agent 正常触发（提及 xlsx/docx/pdf 任务时能加载对应 SKILL.md）。
- requirements.txt 未新增任何包，pip 依赖栈零冲突。
- 所有既有 skill 完好无损，本次改动仅限新增的 skill 目录。
- 验证产生的临时文件已清理，工作区无残留。
```

---

## 附：安装位置速查

| 宿主 | Skill 目录 | 说明 |
|---|---|---|
| Claude Code | `.claude/skills/` | 项目级，也可 `~/.claude/skills/` 全局 |
| 通用 Agent Skills 规范 | `.agents/skills/` | Claude Code / Copilot / Cursor 均认 |
| WorkBuddy 项目级 | `.workbuddy-ai/skills/` | 团队共享 |

建议三处都放同一份，保证任何宿主加载都不落空。

## 附：回滚

```bash
# 只删本次新增的 skill 目录，绝不触碰任何既有 skill
rm -rf .claude/skills/excel-skill .agents/skills/excel-skill
rm -rf .agents/skills/docx .agents/skills/pdf .agents/skills/pptx .agents/skills/xlsx
rm -rf .agents/skills/convert-excel-to-md .agents/skills/convert-word-to-md .agents/skills/convert-pdf-to-md
# document-skills 若走 plugin 安装：
# Claude Code 内执行 /plugin uninstall document-skills@anthropic-agent-skills
# 有 .bak-<日期> 备份的，按需还原备份目录
```
