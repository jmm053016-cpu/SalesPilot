"""将统一报告模型渲染为可下载的 PDF 文档。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Table, TableStyle

from models.analysis import MetricValue
from models.report import ArtifactRef, ReportModel

PDF_MIME = "application/pdf"
FONT_CANDIDATES = (Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"), Path("C:/Windows/Fonts/simhei.ttf"), Path("C:/Windows/Fonts/Deng.ttf"))


def _register_chinese_font() -> str:
    for path in FONT_CANDIDATES:
        if path.exists():
            name = "SalesPilotChinese"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(path)))
            return name
    raise RuntimeError("Chinese font is unavailable")


def _value(value: Any) -> str:
    if isinstance(value, MetricValue):
        return str(value.value) if value.value is not None else (value.reason or "不可用")
    return "不可用" if value is None else str(value)


def _label(name: str) -> str:
    return {"sales": "销售额", "net_sales": "净销售额", "orders": "订单数", "gross_profit": "毛利", "gross_margin": "毛利率"}.get(name, name)


def _header_footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont(document.font_name, 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(18 * mm, 10 * mm, "SalesPilot 销售经营分析报告")
    canvas.drawRightString(192 * mm, 10 * mm, f"第 {document.page} 页")
    canvas.restoreState()


def _styles(font_name: str):
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("SalesPilotTitle", parent=styles["Title"], fontName=font_name, fontSize=18, leading=23, alignment=TA_CENTER, spaceAfter=10),
        "h1": ParagraphStyle("SalesPilotH1", parent=styles["Heading1"], fontName=font_name, fontSize=13, leading=17, spaceBefore=9, spaceAfter=5),
        "h2": ParagraphStyle("SalesPilotH2", parent=styles["Heading2"], fontName=font_name, fontSize=11, leading=14, spaceBefore=5, spaceAfter=3),
        "body": ParagraphStyle("SalesPilotBody", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=14, wordWrap="CJK", spaceAfter=3),
    }


def _table(data, font_name: str, widths=None):
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font_name), ("FONTSIZE", (0, 0), (-1, -1), 8), ("LEADING", (0, 0), (-1, -1), 11), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2F8")), ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB7B8")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return table


def export_pdf(report: ReportModel, output_dir: Path) -> ArtifactRef:
    font_name = _register_chinese_font()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report.report_id}.pdf"
    styles = _styles(font_name)
    document = BaseDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=17 * mm)
    document.font_name = font_name
    frame = Frame(document.leftMargin, document.bottomMargin, document.width, document.height, id="normal")
    document.addPageTemplates([PageTemplate(id="report", frames=[frame], onPage=_header_footer)])
    story = [Paragraph(report.metadata.title if report.metadata else "销售经营分析报告", styles["title"]), Paragraph(f"分析期间：{report.period.start} 至 {report.period.end}", styles["body"]), Paragraph("数据范围与质量", styles["h1"]), Paragraph(f"数据集：{report.dataset_id}", styles["body"])]
    warnings = report.metadata.warnings if report.metadata else []
    story += [Paragraph(warning, styles["body"]) for warning in warnings] or [Paragraph("未记录数据质量警告。", styles["body"])]
    story.append(Paragraph("核心指标", styles["h1"]))
    rows = [["指标", "数值", "口径/说明"]]
    rows.extend([[_label(name), _value(metric), metric.unit if metric.value is not None else (metric.reason or "不可用")] for name, metric in report.analysis.metrics.items()] if report.analysis else [["分析结果", "不可用", "缺少结构化分析结果"]])
    story.append(_table(rows, font_name, [42 * mm, 38 * mm, 88 * mm]))
    story.append(Paragraph("期间变化", styles["h1"]))
    comparisons = report.analysis.comparisons if report.analysis else []
    story.extend([Paragraph(f"{item.dimension}：当前 {_value(item.current)}，对比期 {_value(item.previous)}，变化 {_value(item.change)}。", styles["body"]) for item in comparisons] or [Paragraph("暂无可用期间对比数据。", styles["body"])])
    story.append(Paragraph("品类/产品/区域表现", styles["h1"]))
    rankings = report.analysis.rankings if report.analysis else []
    if rankings:
        for ranking in rankings:
            story.append(Paragraph(f"{ranking.dimension}（指标：{ranking.metric}）", styles["body"]))
            keys = list(dict.fromkeys(key for item in ranking.items for key in item))
            story.append(_table([keys] + [[_value(item.get(key)) for key in keys] for item in ranking.items], font_name))
    else:
        story.append(Paragraph("暂无可用排名数据。", styles["body"]))
    story.append(Paragraph("异常", styles["h1"]))
    anomalies = report.analysis.anomalies if report.analysis else []
    story.extend([Paragraph(f"{item.dimension}：当前值 {_value(item.current_value)}，严重程度 {item.severity}。{item.reason or ''}", styles["body"]) for item in anomalies] or [Paragraph("未发现可报告的异常。", styles["body"])])
    story.append(Paragraph("经营解读", styles["h1"]))
    if report.narrative:
        story.append(Paragraph(report.narrative.summary, styles["body"]))
        story.append(Paragraph("建议", styles["h2"]))
        story.extend([Paragraph(item.text, styles["body"]) for item in report.narrative.recommendations] or [Paragraph("暂无建议。", styles["body"])])
        if report.narrative.hypotheses:
            story.append(Paragraph("待验证假设", styles["h2"]))
            story.extend(Paragraph(item, styles["body"]) for item in report.narrative.hypotheses)
    else:
        story.append(Paragraph("经营解读暂不可用，报告保留确定性分析结果。", styles["body"]))
    story += [Paragraph("指标口径附录", styles["h1"]), Paragraph("报告中的数值均来自 ReportModel 中的确定性分析结果；不可用指标保留其原因，不进行估算。", styles["body"])]
    document.build(story)
    return ArtifactRef(artifact_id=f"{report.report_id}_pdf", kind="report", mime_type=PDF_MIME, display_name=path.name, storage_key=str(path))
