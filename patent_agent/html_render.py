"""Pass 3 — HTML assembly.

Pure Python. No API calls. Reads the Pass 1 understanding dict and the
list of generated SVG file names, emits a single HTML file with the
SVGs referenced via <object> tags (multi-file output).

Bilingual layout mirrors the paragraph-paired pattern from the existing
translator output at backup/US-20260121885-A1_zh.html — English block
immediately followed by `<p class="zh-translation">` Chinese block.
"""

import datetime as _dt
import html as _html
from typing import Any, Optional


_BASE_CSS = """
* { box-sizing: border-box; }
body {
    max-width: 1200px;
    margin: 0 auto;
    padding: 32px 24px 80px;
    font-family: Georgia, "Times New Roman", serif;
    color: #222;
    line-height: 1.65;
    font-size: 16px;
}
header {
    border-bottom: 2px solid #2196F3;
    padding-bottom: 20px;
    margin-bottom: 32px;
}
header .meta {
    color: #666;
    font-size: 13px;
    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    margin-bottom: 12px;
}
header .meta span { margin-right: 18px; }
h1 { margin: 0 0 4px; font-size: 28px; color: #0d47a1; }
h2 { margin: 28px 0 8px; font-size: 22px; color: #1565c0; border-bottom: 1px solid #e0e0e0; padding-bottom: 6px; }
h2.zh-translation {
    font-size: 20px;
    background-color: transparent;
    border-left: none;
    padding: 0;
    margin: 4px 0 20px;
    color: #0d47a1;
}
h3 { margin: 24px 0 4px; font-size: 18px; color: #1976d2; }
h3.zh-translation {
    font-size: 17px;
    background-color: transparent;
    border-left: none;
    padding: 0;
    margin: 0 0 14px;
    color: #1565c0;
}
section { margin-bottom: 36px; }
p { margin: 8px 0; }
/* zh-translation block — copied verbatim from backup/US-20260121885-A1_zh.html lines 8-17 */
.zh-translation {
    background-color: #f0f7ff;
    border-left: 4px solid #2196F3;
    padding: 10px 15px;
    margin: 8px 0 16px 0;
    font-family: "Microsoft YaHei", "SimSun", "PingFang SC", sans-serif;
    color: #1a1a2e;
    line-height: 1.8;
    font-size: 14px;
}
table.component-table, table.interaction-table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0 24px;
    font-size: 14px;
}
table.component-table th, table.interaction-table th {
    background: #e3f2fd;
    text-align: left;
    padding: 8px 10px;
    border: 1px solid #bbdefb;
    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    color: #0d47a1;
}
table.component-table td, table.interaction-table td {
    padding: 8px 10px;
    border: 1px solid #e3f2fd;
    vertical-align: top;
}
table.component-table tr:nth-child(even) td,
table.interaction-table tr:nth-child(even) td {
    background: #fafbff;
}
.bilingual-cell .en { display: block; color: #222; }
.bilingual-cell .zh {
    display: block;
    font-family: "Microsoft YaHei", "SimSun", "PingFang SC", sans-serif;
    color: #455a64;
    font-size: 13px;
    margin-top: 2px;
}
.role-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-family: "Segoe UI", monospace;
    background: #eceff1;
    color: #37474f;
}
.diagram-section object {
    display: block;
    margin: 8px auto 4px;
    max-width: 100%;
    border: 1px solid #e0e0e0;
    background: #fafafa;
}
.diagram-section .caption {
    text-align: center;
    color: #555;
    font-size: 13px;
    margin: 4px 0 12px;
    font-style: italic;
}
.claim-block {
    border-left: 4px solid #ff9800;
    background: #fff8e1;
    padding: 10px 15px;
    margin: 12px 0;
}
.claim-block.high { border-left-color: #f44336; background: #ffebee; }
.claim-block.medium { border-left-color: #ff9800; background: #fff8e1; }
.claim-block.low { border-left-color: #9e9e9e; background: #f5f5f5; }
.importance-badge {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 11px;
    font-family: "Segoe UI", sans-serif;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-left: 8px;
    vertical-align: middle;
}
.importance-badge.high { background: #f44336; color: #fff; }
.importance-badge.medium { background: #ff9800; color: #fff; }
.importance-badge.low { background: #9e9e9e; color: #fff; }
ul.novel-list li { margin-bottom: 12px; }
footer {
    border-top: 1px solid #e0e0e0;
    margin-top: 48px;
    padding-top: 16px;
    color: #888;
    font-size: 12px;
    font-family: "Segoe UI", monospace;
}
"""


def _esc(s: Any) -> str:
    """HTML-escape an arbitrary value coerced to string."""
    return _html.escape(str(s) if s is not None else "", quote=True)


def _bilingual_paragraph(en: str, zh: str) -> str:
    return f"<p>{_esc(en)}</p>\n<p class=\"zh-translation\">{_esc(zh)}</p>"


def _bilingual_heading(level: int, prefix: str, en: str, zh: str) -> str:
    tag = f"h{level}"
    return (
        f"<{tag}>{_esc(prefix)}{_esc(en)}</{tag}>\n"
        f"<{tag} class=\"zh-translation\">{_esc(prefix)}{_esc(zh)}</{tag}>"
    )


def _components_table(components: list[dict[str, Any]]) -> str:
    if not components:
        return "<p><em>No components extracted.</em></p>"
    rows = []
    for c in components:
        rows.append(
            "<tr>"
            f"<td><code>{_esc(c.get('id'))}</code></td>"
            f"<td class=\"bilingual-cell\">"
            f"<span class=\"en\">{_esc(c.get('name_en'))}</span>"
            f"<span class=\"zh\">{_esc(c.get('name_zh'))}</span></td>"
            f"<td class=\"bilingual-cell\">"
            f"<span class=\"en\">{_esc(c.get('description_en'))}</span>"
            f"<span class=\"zh\">{_esc(c.get('description_zh'))}</span></td>"
            f"<td><span class=\"role-badge\">{_esc(c.get('role'))}</span></td>"
            "</tr>"
        )
    return (
        "<table class=\"component-table\">"
        "<thead><tr>"
        "<th>ID</th><th>Name / 名称</th><th>Description / 描述</th><th>Role</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _interactions_table(interactions: list[dict[str, Any]]) -> str:
    if not interactions:
        return "<p><em>No interactions extracted.</em></p>"
    rows = []
    for i in interactions:
        rows.append(
            "<tr>"
            f"<td><code>{_esc(i.get('id'))}</code></td>"
            f"<td><code>{_esc(i.get('from_component'))}</code></td>"
            f"<td><code>{_esc(i.get('to_component'))}</code></td>"
            f"<td class=\"bilingual-cell\">"
            f"<span class=\"en\">{_esc(i.get('label_en'))}</span>"
            f"<span class=\"zh\">{_esc(i.get('label_zh'))}</span></td>"
            f"<td>{_esc(i.get('data_or_signal'))}</td>"
            f"<td>{_esc(i.get('sequence_hint'))}</td>"
            "</tr>"
        )
    return (
        "<table class=\"interaction-table\">"
        "<thead><tr>"
        "<th>ID</th><th>From</th><th>To</th><th>Label / 标签</th>"
        "<th>Data / Signal</th><th>Seq</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _diagrams_section(diagrams: list[dict[str, Any]]) -> str:
    if not diagrams:
        return "<p><em>No diagrams generated.</em></p>"
    parts = []
    for idx, d in enumerate(diagrams, start=1):
        did = _esc(d.get("id"))
        en_title = _esc(d.get("title_en"))
        zh_title = _esc(d.get("title_zh"))
        purpose_en = _esc(d.get("purpose_en"))
        purpose_zh = _esc(d.get("purpose_zh"))
        dtype = _esc(d.get("type"))
        parts.append(
            f"<div class=\"diagram-section\" id=\"diagram-{did}\">"
            f"<h3>Figure {idx}. {en_title} <span class=\"role-badge\">{dtype}</span></h3>"
            f"<h3 class=\"zh-translation\">图 {idx}. {zh_title}</h3>"
            f"<object data=\"figures/{did}.svg\" type=\"image/svg+xml\" width=\"1200\" height=\"800\">"
            f"<img src=\"figures/{did}.svg\" alt=\"{en_title}\" width=\"1200\" height=\"800\">"
            f"</object>"
            f"<div class=\"caption\">{purpose_en}</div>"
            f"<p class=\"zh-translation\">{purpose_zh}</p>"
            f"</div>"
        )
    return "\n".join(parts)


def _claims_section(claims: list[dict[str, Any]]) -> str:
    if not claims:
        return "<p><em>No key claims extracted.</em></p>"
    parts = []
    for c in claims:
        importance = (c.get("importance") or "medium").lower()
        if importance not in ("high", "medium", "low"):
            importance = "medium"
        parts.append(
            f"<div class=\"claim-block {importance}\">"
            f"<span class=\"importance-badge {importance}\">{importance}</span>"
            f"<p>{_esc(c.get('claim_text_en'))}</p>"
            f"<p class=\"zh-translation\">{_esc(c.get('claim_text_zh'))}</p>"
            f"</div>"
        )
    return "\n".join(parts)


def _novel_section(aspects: list[dict[str, Any]]) -> str:
    if not aspects:
        return "<p><em>No novel aspects extracted.</em></p>"
    items = []
    for a in aspects:
        items.append(
            "<li>"
            f"<div>{_esc(a.get('aspect_en'))}</div>"
            f"<div class=\"zh-translation\">{_esc(a.get('aspect_zh'))}</div>"
            "</li>"
        )
    return f"<ul class=\"novel-list\">{''.join(items)}</ul>"


def render_html(
    data: dict[str, Any],
    *,
    patent_stem: str,
    model: str,
    total_cache_read_tokens: int,
    total_input_tokens: int,
    total_output_tokens: int,
    metadata_header: Optional[dict[str, str]] = None,
) -> str:
    """Render the full HTML document. `data` must conform to PATENT_SCHEMA."""

    title_en = _esc(data.get("title_en"))
    title_zh = _esc(data.get("title_zh"))

    meta_bits = []
    if metadata_header:
        for k, v in metadata_header.items():
            meta_bits.append(f"<span><strong>{_esc(k)}:</strong> {_esc(v)}</span>")
    meta_bits.append(f"<span><strong>Patent:</strong> {_esc(patent_stem)}</span>")

    abstract = _bilingual_paragraph(data.get("abstract_en", ""), data.get("abstract_zh", ""))
    background = _bilingual_paragraph(data.get("background_en", ""), data.get("background_zh", ""))

    components_html = _components_table(data.get("components", []))
    interactions_html = _interactions_table(data.get("interactions", []))
    diagrams_html = _diagrams_section(data.get("diagrams", []))
    claims_html = _claims_section(data.get("key_claims", []))
    novel_html = _novel_section(data.get("novel_aspects", []))

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title_en} | {title_zh}</title>
<style>
{_BASE_CSS}
</style>
</head>
<body>
<header>
<div class="meta">{''.join(meta_bits)}</div>
<h1>{title_en}</h1>
<h2 class="zh-translation">{title_zh}</h2>
</header>

<section id="abstract">
{_bilingual_heading(2, "", "Abstract", "摘要")}
{abstract}
</section>

<section id="background">
{_bilingual_heading(2, "", "Background", "背景")}
{background}
</section>

<section id="components">
{_bilingual_heading(2, "", "System Components", "系统组件")}
{components_html}
</section>

<section id="interactions">
{_bilingual_heading(2, "", "Component Interactions", "组件交互")}
{interactions_html}
</section>

<section id="diagrams">
{_bilingual_heading(2, "", "System Interaction Diagrams", "系统交互图")}
{diagrams_html}
</section>

<section id="claims">
{_bilingual_heading(2, "", "Key Claims", "关键权利要求")}
{claims_html}
</section>

<section id="novel">
{_bilingual_heading(2, "", "Novel Aspects", "新颖之处")}
{novel_html}
</section>

<footer>
Generated by patent_agent &mdash; model: {_esc(model)} &mdash; generated: {now}<br>
Tokens: input {total_input_tokens:,} &middot; output {total_output_tokens:,} &middot; cache reads {total_cache_read_tokens:,}
</footer>
</body>
</html>
"""
