# SalesPilot

**语言：** [English](README.md) | 简体中文

**一个具备会话隔离能力的销售分析工作台，可将 CSV、Excel 和 SQLite 数据转换为可解释的分析结果及可下载的业务报告。**

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-ff4b4b?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[GitHub](https://github.com/jmm053016-cpu/SalesPilot) · [Gitee 镜像](https://gitee.com/gold-m/sales-pilot)

SalesPilot 将确定性的销售指标计算与可选的大语言模型助手结合。应用会校验导入的数据，明确展示可计算的指标，并将分析结果导出为 Word 或 PDF 报告。语言模型可用于文字解读和后续问答，但不会计算或编造数值结果。

## 界面预览

![SalesPilot 数据源工作台](screenshots/salespilot-workbench.png)

截图展示了当前版本在上传数据集前的数据源工作台。应用支持 CSV、Excel 和 SQLite 数据源，并引导用户依次完成字段校验、分析配置、结果洞察和报告导出。

## 功能

- 导入 CSV、Excel 文件，或连接受支持的 SQLite 数据源。
- 将常见列名映射到统一销售数据结构，并在分析前校验日期、金额、币种和数据粒度。
- 根据可用字段计算销售额、净销售额、毛利、订单数、周期对比、排名和异常。
- 对缺少数据支持的指标明确标记为不可用，不估算缺失值。
- 将报告和配套图表导出为 Word 或 PDF。
- 在会话范围内继续分析，并可选用大语言模型助手进行问答。
- 将助手限制在数据集检查、受控分析请求和报告导出范围内；不接受任意 SQL、Python、文件路径或用户代码。

## 环境要求

- Python 3.12
- 大语言模型 API 密钥为可选项。无密钥时仍可使用确定性分析和报告生成；文字解读和后续问答需要配置模型服务。

## 快速开始

克隆任一仓库：

```bash
git clone https://github.com/jmm053016-cpu/SalesPilot.git
cd SalesPilot
```

也可以克隆 Gitee 镜像：

```bash
git clone https://gitee.com/gold-m/sales-pilot.git
cd sales-pilot
```

创建并启用虚拟环境：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS 或 Linux：

```bash
source .venv/bin/activate
```

安装依赖并启动：

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

打开 Streamlit 输出的本地地址，通常为 `http://localhost:8501`。

## 配置

将 `.env.example` 复制为 `.env`，并填入所需服务商的凭据。请勿提交 `.env`；该文件已在 `.gitignore` 中排除。

| 变量 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 启用 DeepSeek 报告文字解读和后续对话。 |
| `DEEPSEEK_MODEL` | DeepSeek 模型名称，默认值为 `deepseek-flash`。 |
| `DEEPSEEK_BASE_URL` | DeepSeek 兼容 API 地址，默认值为 `https://api.deepseek.com`。 |
| `TAVILY_API_KEY` | 可选。配置后启用 Agent 网页搜索，用于补充行业、市场和竞争背景。 |

没有 DeepSeek 凭据时，确定性分析和报告导出仍可使用；模型辅助的文字解读和后续问答将不可用。没有 Tavily 凭据时，Agent 仍可使用本地数据导入、确定性分析和报告工具，只是不会进行网页搜索。网页搜索仅用于外部背景检索，不参与销售指标计算，也不能替代当前数据集中的事实。

## 数据与分析

导入流程会预览源数据、映射可识别的列名、校验所选数据粒度，并报告可用指标。支持 CSV 和 Excel 上传。SQLite 访问仅限应用支持的只读数据源查询。

必需字段包括可解析的订单日期和非负销售金额。退款、成本、订单 ID、数量、产品、类别、地区和币种等可选字段可启用更多指标和细分分析。不接受混合币种数据集，应用不会执行货币换算。

分析结果由确定性逻辑计算。例如，净销售额需要退款信息或明确确认没有退款；订单数需要订单粒度数据和订单 ID；毛利需要成本数据。缺少必要输入时会标记为不可用，而不是推断数值。

运行时数据集、分析结果、对话、报告和上传文件存储在 `.runtime/` 下，并从版本控制中排除。数据集访问范围限定于当前会话。

## 测试

运行确定性测试套件：

```bash
python -m pytest -q
```

测试覆盖数据导入与校验、分析指标、排名与对比、助手边界、会话与对话行为，以及报告生成。

测试使用本地 fixtures，不需要调用在线模型 API。若在启用模型辅助功能时配置 API 密钥，运行应用可能产生实际费用。

## 项目结构

```text
app.py              Streamlit 应用入口
agent/              助手运行时、提示词和受控分析工具
analytics/          确定性指标、对比、排名和异常分析
charts/             销售图表生成
data_sources/       CSV、Excel、SQLite 导入、映射和校验
models/             数据、分析、报告和对话模型
reports/            Word/PDF 报告生成与产物校验
storage/            会话级数据集、分析、对话和产物存储
ui/                 数据录入、分析工作台、结果和后续问答界面
workflow/           从分析到报告的工作流
tests/              单元测试、工作流测试和示例 fixtures
```

## 许可证

SalesPilot 根据 [MIT 许可证](LICENSE) 发布。
