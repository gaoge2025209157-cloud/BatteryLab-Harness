"""Create a self-contained, UTF-8 research report for non-code users."""

from __future__ import annotations

import base64
from html import escape
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _e(value: Any) -> str:
    return escape(_text(value))


def _list(items: Sequence[Any], formatter=None, empty="暂无可核验内容。") -> str:
    if not items:
        return '<p class="empty">{}</p>'.format(escape(empty))
    rows = []
    for item in items:
        content = formatter(item) if formatter else _e(item)
        rows.append("<li>{}</li>".format(content))
    return "<ul>{}</ul>".format("".join(rows))


def _doi_link(value: Any) -> str:
    doi = _text(value)
    if not doi:
        return "来源待核对"
    safe_url = "https://doi.org/" + quote(doi, safe="/:._-()")
    return '<a href="{}">{}</a>'.format(escape(safe_url, quote=True), escape(doi))


def _embedded_images(image_paths: Sequence[Path]) -> str:
    cards = []
    for path in image_paths:
        candidate = Path(path)
        if not candidate.is_file() or candidate.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".gif", ".svg"}:
            continue
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
        }[candidate.suffix.casefold()]
        encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
        cards.append(
            '<figure><img src="data:{};base64,{}" alt="{}"><figcaption>{}</figcaption></figure>'.format(
                mime, encoded, escape(candidate.stem, quote=True), escape(candidate.stem)
            )
        )
    if not cards:
        return '<p class="empty">本轮未生成可嵌入图像。数据结论仍保留，绘图失败或未启用时请查看运行记录。</p>'
    return '<div class="figure-grid">{}</div>'.format("".join(cards))


def create_research_html_report(
    target: Path | str,
    *,
    values: Mapping[str, Any],
    deterministic_text: str,
    guidance_text: str,
    reasoning: Mapping[str, Any] | None = None,
    status_by_id: Mapping[str, str] | None = None,
    papers: Sequence[Mapping[str, Any]] = (),
    image_paths: Sequence[Path] = (),
) -> Path:
    """Write one portable report with embedded figures and no external assets."""

    from .knowledge_assistant import knowledge_candidate_key

    reasoning = dict(reasoning or {})
    statuses = dict(status_by_id or {})
    profile_rows = []
    for key, label, unit in (
        ("battery_system", "电池体系", ""),
        ("active_material", "活性物质", ""),
        ("cell_type", "电池类型", ""),
        ("counter_electrode", "对电极", ""),
        ("test_current", "测试电流", "mA"),
        ("temperature", "测试温度", "°C"),
        ("research_domain", "研究领域", ""),
        ("research_question", "科学问题", ""),
    ):
        value = _text(values.get(key))
        if value:
            profile_rows.append("<tr><th>{}</th><td>{}{}</td></tr>".format(escape(label), escape(value), escape(" " + unit if unit else "")))

    paper_rows = []
    for index, paper in enumerate(papers, 1):
        paper_rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                index,
                _e(paper.get("title")) or "未命名文献",
                _e(paper.get("journal")),
                _e(paper.get("year")),
                _doi_link(paper.get("doi")),
            )
        )

    findings = _list(
        reasoning.get("article_core_findings", []),
        lambda item: "<strong>{}</strong><br>{}<br><span class=\"muted\">方法：{}；正文位置：{}；限制：{}</span>".format(
            _doi_link(item.get("source_id")), _e(item.get("core_finding")), _e(item.get("method")),
            _e(item.get("evidence_location")), _e(item.get("limitations")),
        ),
        "本轮没有取得可读取原文，因此没有生成原文知识。",
    )
    backgrounds = _list(
        reasoning.get("research_background", []),
        lambda item: "{}<br><span class=\"muted\">来源：{}；边界：{}</span>".format(
            _e(item.get("claim")), "、".join(_doi_link(value) for value in item.get("source_ids", [])), _e(item.get("limitations"))
        ),
    )
    foundations = _list(
        reasoning.get("electrochemistry_foundations", []),
        lambda item: "<strong>{}</strong>：{}<br><span class=\"muted\">适用边界：{}</span>".format(
            _e(item.get("concept")), _e(item.get("explanation")), _e(item.get("boundaries"))
        ),
    )
    assessments = _list(
        reasoning.get("data_value_assessment", []),
        lambda item: "<strong>{}</strong>：{}<br><span class=\"muted\">依据：{}；置信度：{}；限制：{}</span>".format(
            _e(item.get("finding")), _e(item.get("value")), _e(item.get("evidence")),
            _e(item.get("confidence")), _e(item.get("limitations"))
        ),
    )
    experiments = _list(
        reasoning.get("missing_experiments", []),
        lambda item: "<strong>{}</strong>：{}<br><span class=\"muted\">变量与对照：{}；支持/反证：{}</span>".format(
            _e(item.get("question")), _e(item.get("experiment")), _e(item.get("variables")), _e(item.get("expected_evidence"))
        ),
    )
    characterizations = _list(
        reasoning.get("missing_characterization", []),
        lambda item: "<strong>{}</strong>：{}<br><span class=\"muted\">取样：{}；支持/反证：{}</span>".format(
            _e(item.get("question")), _e(item.get("characterization")), _e(item.get("sampling")), _e(item.get("expected_evidence"))
        ),
    )
    candidate_rows = []
    for item in reasoning.get("knowledge_candidates", []):
        candidate_id = knowledge_candidate_key(item)
        status = statuses.get(candidate_id, "candidate")
        labels = {"approved": "已人工确认", "rejected": "已拒绝", "candidate": "已学习·待复核"}
        candidate_rows.append(
            '<tr><td><span class="pill {}">{}</span></td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                escape(status), escape(labels.get(status, status)), _e(item.get("claim")),
                "、".join(_doi_link(value) for value in item.get("source_ids", [])), _e(item.get("conditions"))
            )
        )

    template = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>电化学研究分析报告</title>
<style>
:root{--ink:#18212d;--muted:#5c6878;--line:#dce3eb;--panel:#fff;--soft:#f4f7fa;--blue:#1f5f8b;--teal:#217a70;--amber:#a16816;--red:#a23b3b}*{box-sizing:border-box}body{margin:0;background:var(--soft);color:var(--ink);font-family:"Microsoft YaHei UI","PingFang SC",Arial,sans-serif;line-height:1.72}.wrap{max-width:1180px;margin:auto;padding:28px}.hero{padding:28px 32px;border-radius:18px;background:linear-gradient(135deg,#18344d,#276f75);color:#fff;box-shadow:0 12px 30px #18344d22}.hero h1{margin:0 0 8px;font-size:30px}.hero p{margin:0;color:#e8f3f4}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px 22px;box-shadow:0 5px 20px #25354a0b}.wide{grid-column:1/-1}h2{font-size:20px;margin:0 0 12px;color:var(--blue)}h3{font-size:16px;margin:18px 0 8px;color:var(--teal)}table{width:100%;border-collapse:collapse;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:9px 8px;text-align:left;vertical-align:top}th{color:var(--muted);width:150px}ul{margin:8px 0;padding-left:22px}li{margin:8px 0}.plain{white-space:pre-wrap;background:#f8fafc;border-left:4px solid var(--blue);padding:14px 16px;border-radius:8px}.muted,.empty{color:var(--muted)}.pill{display:inline-block;padding:2px 9px;border-radius:999px;background:#edf2f7;white-space:nowrap}.pill.approved{background:#e0f2ec;color:#17634f}.pill.rejected{background:#f9e6e6;color:#8b2828}.pill.candidate{background:#fff0d5;color:#8b5b10}.figure-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:0;border:1px solid var(--line);border-radius:12px;padding:10px;background:#fff}img{display:block;max-width:100%;height:auto;margin:auto}figcaption{text-align:center;color:var(--muted);padding-top:8px}.foot{text-align:center;color:var(--muted);padding:24px 0}@media(max-width:760px){.wrap{padding:12px}.grid,.figure-grid{grid-template-columns:1fr}.hero{padding:22px}.hero h1{font-size:24px}}@media print{body{background:#fff}.wrap{max-width:none;padding:0}.hero,.card{box-shadow:none}.card{break-inside:avoid}}
</style></head><body><main class="wrap">
<section class="hero"><h1>电化学研究分析报告</h1><p>实验数据、原文调研、本地大模型学习与课题建议的一体化结果</p></section>
<div class="grid">
<section class="card"><h2>实验与课题配置</h2><table>{profile}</table></section>
<section class="card"><h2>自动调研概况</h2><p>{summary}</p><p class="muted">文献提炼默认标记为“已学习·待复核”。它可以用于形成候选解释和下一轮实验，但不能单独证明本实验机理。</p></section>
<section class="card wide"><h2>关键图像</h2>{images}</section>
<section class="card wide"><h2>确定性数据结论</h2><div class="plain">{deterministic}</div></section>
<section class="card wide"><h2>本轮真实文献</h2><table><thead><tr><th>#</th><th>题名</th><th>期刊</th><th>年份</th><th>DOI</th></tr></thead><tbody>{papers}</tbody></table></section>
<section class="card"><h2>逐篇原文核心发现</h2>{findings}</section>
<section class="card"><h2>领域背景知识</h2>{backgrounds}</section>
<section class="card"><h2>电化学专业知识</h2>{foundations}</section>
<section class="card"><h2>数据与文献联合判断</h2>{assessments}</section>
<section class="card"><h2>下一轮判别实验</h2>{experiments}</section>
<section class="card"><h2>表征与取样</h2>{characterizations}</section>
<section class="card wide"><h2>已学习知识与复核状态</h2><table><thead><tr><th>状态</th><th>知识点</th><th>来源</th><th>适用条件</th></tr></thead><tbody>{candidates}</tbody></table></section>
<section class="card wide"><h2>完整课题指导</h2><div class="plain">{guidance}</div></section>
</div><p class="foot">本报告使用 UTF-8 编码且不依赖外部资源。结论应结合平行样、对照实验和原始文献复核。</p>
</main></body></html>"""
    replacements = {
        "{profile}": "".join(profile_rows),
        "{summary}": _e(reasoning.get("summary")) or "本轮未形成原文学习摘要。",
        "{images}": _embedded_images(image_paths),
        "{deterministic}": escape(str(deterministic_text or "")),
        "{papers}": "".join(paper_rows) or '<tr><td colspan="5" class="empty">本轮没有可显示的真实题录。</td></tr>',
        "{findings}": findings,
        "{backgrounds}": backgrounds,
        "{foundations}": foundations,
        "{assessments}": assessments,
        "{experiments}": experiments,
        "{characterizations}": characterizations,
        "{candidates}": "".join(candidate_rows) or '<tr><td colspan="4" class="empty">本轮没有知识候选。</td></tr>',
        "{guidance}": escape(str(guidance_text or "")),
    }
    html = template
    for marker, content in replacements.items():
        html = html.replace(marker, content)
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8-sig")
    return destination
