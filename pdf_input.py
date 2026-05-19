"""PDF input pipeline.

We extract full text + render only a handful of figure-heavy pages, then
ship that as a sequence of content blocks. Total request body is engineered
to stay under ~800 KB so it fits within a typical nginx 1 MB proxy limit.

Cache strategy (OpenAI prompt cache, automatic):
- The block list is byte-identical across Pass 1 and every Pass 2 call.
- OpenAI's prompt cache kicks in automatically on stable prefixes
  >= 1024 tokens that recur within a short window.
- Per-call instruction text is appended AFTER this stable prefix so the
  prefix is reused; the only thing that changes per call is the trailing
  instruction.
"""

import base64
import hashlib
import os
import re
from typing import Any


def load_pdf_meta(pdf_path: str) -> tuple[bytes, str]:
    """Read raw PDF bytes and compute SHA256 (cache-key derivation)."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    with open(pdf_path, "rb") as f:
        raw = f.read()
    return raw, hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Page scoring + selection
# ---------------------------------------------------------------------------


def _page_score(page: Any, page_idx: int) -> int:
    """Score a page by likelihood of being a figure page.

    Heuristics:
    - Embedded raster images (e.g. scanned figures): strong signal.
    - Many vector drawings (USPTO figures are often vector): medium signal.
    - Sparse text relative to page area: weak signal.
    - Pages near the front of the patent (figures are typically pp 2-6).
    """
    text_len = len(page.get_text("text"))
    image_count = len(page.get_images())
    try:
        drawing_count = len(page.get_drawings())
    except Exception:
        drawing_count = 0

    score = 0
    if image_count > 0:
        score += 20 + min(image_count, 5)
    if drawing_count > 50:
        score += 15
    elif drawing_count > 5:
        score += 5

    if text_len < 400:
        score += 10
    elif text_len < 1500:
        score += 3

    # Position prior: figures usually live in the first few pages.
    if 1 <= page_idx <= 5:
        score += 2
    return score


def select_figure_pages(doc: Any, max_pages: int = 6) -> list[int]:
    """Return up to `max_pages` 0-based page indices, sorted ascending."""
    scored: list[tuple[int, int]] = []
    for i, page in enumerate(doc):
        s = _page_score(page, i)
        if s > 0:
            scored.append((s, i))
    # Sort: highest score first; tie-break by earliest page index.
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = sorted(idx for _, idx in scored[:max_pages])
    return chosen


# ---------------------------------------------------------------------------
# Text + figure extraction
# ---------------------------------------------------------------------------


def _clean_text(text: str) -> str:
    # Collapse internal whitespace runs and excessive blank lines.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_and_figures(
    pdf_bytes: bytes,
    max_figure_pages: int = 6,
    dpi: int = 96,
    image_format: str = "jpeg",
    jpeg_quality: int = 80,
) -> tuple[str, list[dict[str, Any]]]:
    """Extract full text and render selected figure pages.

    Returns:
        (text, figures)
        text: cleaned full text of the PDF with `--- Page N ---` markers.
        figures: list of dicts {page: int(1-based), media_type: str, data_b64: str}.
    """
    import fitz  # type: ignore

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        # 1. Text extraction (all pages)
        text_parts: list[str] = []
        for i, page in enumerate(doc):
            page_text = page.get_text("text")
            text_parts.append(f"--- Page {i + 1} ---\n{page_text.strip()}")
        full_text = _clean_text("\n\n".join(text_parts))

        # 2. Figure page selection + render
        selected = select_figure_pages(doc, max_pages=max_figure_pages)
        figures: list[dict[str, Any]] = []
        for idx in selected:
            page = doc[idx]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            if image_format.lower() in ("jpeg", "jpg"):
                try:
                    img_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
                    media_type = "image/jpeg"
                except (TypeError, ValueError):
                    # Older PyMuPDF: fall back to PNG.
                    img_bytes = pix.tobytes("png")
                    media_type = "image/png"
            else:
                img_bytes = pix.tobytes("png")
                media_type = "image/png"
            b64 = base64.standard_b64encode(img_bytes).decode("ascii")
            figures.append({
                "page": idx + 1,
                "media_type": media_type,
                "data_b64": b64,
                "raw_bytes_len": len(img_bytes),
            })
    finally:
        doc.close()

    return full_text, figures


# ---------------------------------------------------------------------------
# Content-block construction (OpenAI Chat Completions multimodal shape)
# ---------------------------------------------------------------------------


def _render_page_jpeg(page: Any, dpi: int, jpeg_quality: int) -> tuple[bytes, str]:
    """Render one page; falls back to PNG on older PyMuPDF that can't emit JPEG."""
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    try:
        return pix.tobytes("jpeg", jpg_quality=jpeg_quality), "image/jpeg"
    except (TypeError, ValueError):
        return pix.tobytes("png"), "image/png"


def render_for_scan_pdf(
    pdf_bytes: bytes,
    target_payload_bytes: int = 800_000,
    dpis: tuple[int, ...] = (96, 80, 72, 64, 56, 48),
    jpeg_quality: int = 75,
) -> tuple[list[dict[str, Any]], int]:
    """Render every page of a scan-only PDF, auto-picking a DPI that fits the
    payload budget. Returns (figures, chosen_dpi).

    figures has the same shape as `extract_text_and_figures` returns, and is
    safe to feed directly to `build_content_blocks`.
    """
    import fitz  # type: ignore

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        last_figures: list[dict[str, Any]] = []
        last_dpi = dpis[-1]
        for dpi in dpis:
            figures: list[dict[str, Any]] = []
            total_b64 = 0
            for i, page in enumerate(doc):
                img_bytes, media_type = _render_page_jpeg(page, dpi, jpeg_quality)
                b64 = base64.standard_b64encode(img_bytes).decode("ascii")
                total_b64 += len(b64)
                figures.append({
                    "page": i + 1,
                    "media_type": media_type,
                    "data_b64": b64,
                    "raw_bytes_len": len(img_bytes),
                })
            last_figures = figures
            last_dpi = dpi
            # +4 KB slack for JSON wrappers and text block overhead.
            if total_b64 + 4096 <= target_payload_bytes:
                return figures, dpi
        return last_figures, last_dpi
    finally:
        doc.close()


def build_content_blocks(
    text: str,
    figures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble OpenAI Chat Completions multimodal content blocks.

    Order: one text block (full extracted text) -> N image_url blocks
    (rendered figure pages as base64 data URLs).

    OpenAI's prompt caching is automatic for stable prefixes (>= 1024
    tokens) that recur within a short window; no explicit cache marker is
    needed. Keep this block list byte-identical across Pass 1 and every
    Pass 2 call so the cache hits and the prefix is reused.
    """
    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Below is the full text extracted from the patent PDF. "
                "Page boundaries are marked with `--- Page N ---`. After the "
                "text, a small number of figure-heavy pages are attached as "
                "images so you can read the actual diagrams.\n\n"
                + text
            ),
        }
    ]
    for f in figures:
        blocks.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{f['media_type']};base64,{f['data_b64']}",
            },
        })
    return blocks


def estimate_payload_size(blocks: list[dict[str, Any]]) -> int:
    """Rough sum of payload bytes (text + image data URLs)."""
    total = 0
    for b in blocks:
        if b.get("type") == "text":
            total += len(b.get("text", "").encode("utf-8"))
        elif b.get("type") == "image_url":
            total += len(b.get("image_url", {}).get("url", ""))
    return total
