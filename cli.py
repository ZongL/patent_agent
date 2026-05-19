"""CLI orchestrator. Pass 1 -> Pass 2 -> Pass 3."""

import argparse
import json
import os
import re
import sys
from typing import Any, Optional

from patent_agent.cache import ResponseCache
from patent_agent.config import (
    DEFAULT_DPI,
    DEFAULT_MAX_DIAGRAMS,
    DEFAULT_MAX_FIGURE_PAGES,
    DEFAULT_MODEL,
    PROMPT_VERSION,
)
from patent_agent.diagram import run_pass2_one
from patent_agent.html_render import render_html
from patent_agent.pdf_input import (
    build_content_blocks,
    estimate_payload_size,
    extract_text_and_figures,
    load_pdf_meta,
    render_for_scan_pdf,
)
from patent_agent.understand import run_pass1


def _read_text(path: str) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise IOError(f"Could not decode {path}")


def _eprint(*args: Any, **kwargs: Any) -> None:
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)


def _synthesize_overview(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "fig1",
        "title_en": "System Overview",
        "title_zh": "系统概览",
        "purpose_en": "High-level view of all extracted components and their major interactions.",
        "purpose_zh": "所提取的所有组件及其主要交互的高层视图。",
        "type": "system_overview",
        "focused_component_ids": [c["id"] for c in data.get("components", [])],
        "focused_interaction_ids": [i["id"] for i in data.get("interactions", [])],
    }


def _check_pdf_quality(data: dict[str, Any]) -> None:
    """Heuristic: warn if Pass 1 returned suspiciously thin content."""
    abstract = data.get("abstract_en", "")
    if len(abstract) < 50:
        _eprint(
            "WARNING: extracted abstract is very short — the PDF may be "
            "image-only / scanned, or has no extractable text. Quality of "
            "downstream output may be limited."
        )


_PAGE_MARKER_RE = re.compile(r"---\s*Page\s+\d+\s*---", re.IGNORECASE)


def _is_scan_pdf(text: str, threshold: int = 500) -> bool:
    """True when the extracted text is essentially empty (only page markers)."""
    stripped = _PAGE_MARKER_RE.sub("", text).strip()
    return len(stripped) < threshold


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="patent_agent",
        description=(
            "Analyze a USPTO patent PDF with Claude and produce a bilingual "
            "(English + Simplified Chinese) HTML report with model-generated "
            "SVG diagrams."
        ),
    )
    p.add_argument("pdf", help="Path to USPTO patent PDF")
    p.add_argument(
        "--companion-html",
        default=None,
        help="Optional supplementary HTML file (used in Pass 1 only)",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: D:\\uspto\\outputs\\<pdf-stem>)",
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Model ID (default {DEFAULT_MODEL})")
    p.add_argument(
        "--api-key",
        default=None,
        help="API key (overrides ANTHROPIC_API_KEY env var)",
    )
    p.add_argument(
        "--base-url",
        default=None,
        help="API base URL (overrides ANTHROPIC_BASE_URL env var; useful for proxies / Bedrock-compatible gateways)",
    )
    p.add_argument("--force", action="store_true", help="Ignore disk cache; re-run both passes")
    p.add_argument(
        "--skip-svg",
        action="store_true",
        help="Skip Pass 2 (reuse existing SVGs if present, else placeholders)",
    )
    p.add_argument(
        "--max-diagrams",
        type=int,
        default=DEFAULT_MAX_DIAGRAMS,
        help=f"Cap diagrams in Pass 2 (default {DEFAULT_MAX_DIAGRAMS})",
    )
    p.add_argument(
        "--max-figure-pages",
        type=int,
        default=DEFAULT_MAX_FIGURE_PAGES,
        help=f"Max figure-heavy pages rendered as images (default {DEFAULT_MAX_FIGURE_PAGES})",
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"DPI for rendered figure pages (default {DEFAULT_DPI})",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Log per-call usage.cache_read_input_tokens to stderr",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    pdf_path = os.path.abspath(args.pdf)
    if not os.path.exists(pdf_path):
        _eprint(f"ERROR: PDF not found: {pdf_path}")
        return 1

    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    output_dir = args.output_dir or os.path.join(
        os.path.dirname(pdf_path), "outputs", stem
    )
    output_dir = os.path.abspath(output_dir)
    figures_dir = os.path.join(output_dir, "figures")
    cache_dir = os.path.join(output_dir, ".cache")
    os.makedirs(figures_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    if not os.environ.get("OPENAI_API_KEY") and not args.api_key:
        _eprint(
            "ERROR: no API key provided. Set OPENAI_API_KEY env var or use --api-key."
        )
        return 1

    # Defer import so --help works without the SDK installed.
    try:
        import openai  # type: ignore
    except ImportError:
        _eprint("ERROR: openai SDK not installed. Run: pip install openai")
        return 1

    # Build client. Explicit args win over env vars; env vars handled by the SDK
    # automatically if we pass None.
    client_kwargs: dict[str, Any] = {}
    if args.api_key:
        client_kwargs["api_key"] = args.api_key
    effective_base_url = args.base_url or os.environ.get("OPENAI_BASE_URL")
    if args.base_url:
        client_kwargs["base_url"] = args.base_url
    client = openai.OpenAI(**client_kwargs)
    if effective_base_url:
        print(f"Using API base URL: {effective_base_url}")

    # ------------------------------------------------------------------
    # Load inputs
    # ------------------------------------------------------------------
    print(f"Loading PDF: {pdf_path}")
    pdf_bytes, pdf_sha256 = load_pdf_meta(pdf_path)
    print(f"  size: {len(pdf_bytes):,} bytes  sha256: {pdf_sha256[:16]}...")

    print(f"Extracting text + up to {args.max_figure_pages} figure pages @ {args.dpi} DPI...")
    pdf_text, figures = extract_text_and_figures(
        pdf_bytes,
        max_figure_pages=args.max_figure_pages,
        dpi=args.dpi,
    )

    if _is_scan_pdf(pdf_text):
        print(
            "PDF has no extractable digital text (scanned / image-only patent). "
            "Falling back: rendering every page as an image, auto-selecting DPI "
            "to fit the payload budget..."
        )
        figures, chosen_dpi = render_for_scan_pdf(
            pdf_bytes,
            target_payload_bytes=800_000,
        )
        print(f"  rendered {len(figures)} pages at DPI {chosen_dpi}")
        if chosen_dpi <= 56:
            _eprint(
                f"NOTE: chose low DPI ({chosen_dpi}) to fit payload under ~800KB. "
                "Figure detail may be reduced. If your proxy allows >1MB request "
                "bodies, raising the target_payload_bytes constant in cli.py "
                "would give better resolution."
            )
        pdf_text = (
            "(This PDF has no extractable digital text. All pages of the patent "
            "are attached below as rendered page images — read every figure and "
            "every body-text page directly from the images.)"
        )

    content_blocks = build_content_blocks(pdf_text, figures)
    payload_bytes = estimate_payload_size(content_blocks)
    print(
        f"  text: {len(pdf_text):,} chars  figures: {len(figures)} pages  "
        f"payload: ~{payload_bytes:,} bytes"
    )
    if args.verbose:
        for f in figures:
            _eprint(
                f"  figure page={f['page']} media={f['media_type']} "
                f"bytes={f['raw_bytes_len']:,}"
            )
    if payload_bytes > 900_000:
        _eprint(
            f"WARNING: payload ~{payload_bytes:,} bytes is close to or above a "
            f"common 1 MB proxy limit. Reduce --max-figure-pages or --dpi if the "
            f"API returns 413."
        )

    companion_html_text: Optional[str] = None
    if args.companion_html:
        if not os.path.exists(args.companion_html):
            _eprint(f"WARNING: --companion-html not found: {args.companion_html}")
        else:
            companion_html_text = _read_text(args.companion_html)
            print(f"  companion HTML: {len(companion_html_text):,} chars")

    cache = ResponseCache(os.path.join(cache_dir, "responses.json"))

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_create = 0
    svg_failures: list[str] = []

    def _accumulate(usage: dict[str, int]) -> None:
        nonlocal total_input, total_output, total_cache_read, total_cache_create
        total_input += usage.get("input_tokens", 0) or 0
        total_output += usage.get("output_tokens", 0) or 0
        total_cache_read += usage.get("cache_read_input_tokens", 0) or 0
        total_cache_create += usage.get("cache_creation_input_tokens", 0) or 0

    def _log_usage(label: str, usage: dict[str, int]) -> None:
        if args.verbose:
            _eprint(
                f"  [{label}] input={usage.get('input_tokens', 0):,} "
                f"output={usage.get('output_tokens', 0):,} "
                f"cache_create={usage.get('cache_creation_input_tokens', 0):,} "
                f"cache_read={usage.get('cache_read_input_tokens', 0):,}"
            )

    # ------------------------------------------------------------------
    # Pass 1 — Understanding
    # ------------------------------------------------------------------
    p1_key = ResponseCache.make_key(pdf_sha256, PROMPT_VERSION, "understanding")
    data: Optional[dict[str, Any]] = None

    if not args.force and cache.has(p1_key):
        data = cache.get(p1_key)
        print("Pass 1 (understanding): cache hit, skipping API call")
    else:
        print("Pass 1 (understanding): calling Claude...")
        try:
            data, usage = run_pass1(
                client,
                content_blocks=content_blocks,
                companion_html=companion_html_text,
                model=args.model,
            )
        except Exception as e:
            _eprint(f"ERROR: Pass 1 failed: {type(e).__name__}: {e}")
            return 2
        _accumulate(usage)
        _log_usage("pass1", usage)
        cache.put(p1_key, data)
        cache.save()

    assert data is not None
    _check_pdf_quality(data)

    # Persist understanding.json (always — easy for the user to inspect)
    with open(os.path.join(output_dir, "understanding.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Fallback: synthesize one diagram if none were extracted
    diagrams: list[dict[str, Any]] = list(data.get("diagrams", []))
    if not diagrams:
        print("Pass 1 returned no diagrams; synthesizing a system_overview from extracted components.")
        diagrams = [_synthesize_overview(data)]
        data["diagrams"] = diagrams

    # Honour --max-diagrams
    if len(diagrams) > args.max_diagrams:
        print(f"Capping diagrams: {len(diagrams)} -> {args.max_diagrams}")
        diagrams = diagrams[: args.max_diagrams]
        data["diagrams"] = diagrams

    # ------------------------------------------------------------------
    # Pass 2 — Per-diagram SVG
    # ------------------------------------------------------------------
    if args.skip_svg:
        print(f"Pass 2 (SVGs): --skip-svg set, reusing whatever is in {figures_dir}")
    else:
        for idx, diagram in enumerate(diagrams, start=1):
            did = diagram["id"]
            svg_path = os.path.join(figures_dir, f"{did}.svg")
            cache_key = ResponseCache.make_key(pdf_sha256, PROMPT_VERSION, f"svg:{did}")

            if not args.force and cache.has(cache_key) and os.path.exists(svg_path):
                print(f"Pass 2 (fig {idx}/{len(diagrams)} {did}): cache hit")
                continue

            print(
                f"Pass 2 (fig {idx}/{len(diagrams)} {did}, type={diagram.get('type')}): "
                "streaming from Claude..."
            )
            try:
                svg_text, usage, ok = run_pass2_one(
                    client,
                    content_blocks=content_blocks,
                    diagram=diagram,
                    pass1_json=data,
                    model=args.model,
                )
            except Exception as e:
                _eprint(f"ERROR: Pass 2 call for {did} failed: {type(e).__name__}: {e}")
                return 2
            _accumulate(usage)
            _log_usage(f"pass2:{did}", usage)

            if not ok:
                svg_failures.append(did)

            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_text)

            # Persist cache after each SVG so a partial run is recoverable.
            if ok:
                cache.put(cache_key, svg_text)
                cache.save()

    # ------------------------------------------------------------------
    # Pass 3 — HTML assembly
    # ------------------------------------------------------------------
    print("Pass 3 (HTML assembly)...")
    metadata_header = {"Model": args.model}
    html = render_html(
        data,
        patent_stem=stem,
        model=args.model,
        total_cache_read_tokens=total_cache_read,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        metadata_header=metadata_header,
    )
    report_path = os.path.join(output_dir, "report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Write run.log (always)
    with open(os.path.join(output_dir, "run.log"), "w", encoding="utf-8") as f:
        f.write(
            f"model: {args.model}\n"
            f"prompt_version: {PROMPT_VERSION}\n"
            f"input_tokens: {total_input}\n"
            f"output_tokens: {total_output}\n"
            f"cache_creation_input_tokens: {total_cache_create}\n"
            f"cache_read_input_tokens: {total_cache_read}\n"
            f"svg_failures: {svg_failures}\n"
        )

    print()
    print(f"Done.")
    print(f"  Report:        {report_path}")
    print(f"  Understanding: {os.path.join(output_dir, 'understanding.json')}")
    print(f"  Figures:       {figures_dir}")
    print(
        f"  Tokens:        input={total_input:,}  output={total_output:,}  "
        f"cache_read={total_cache_read:,}  cache_create={total_cache_create:,}"
    )
    if svg_failures:
        _eprint(f"  SVG fallbacks used for: {svg_failures}")
        return 3
    return 0
