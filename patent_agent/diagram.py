"""Pass 2 - Per-diagram SVG generation.

One streamed API call per diagram identified in Pass 1. The user content
prefix (text + figure images) is byte-identical to Pass 1, and the system
prompt is constant, so OpenAI's prompt cache reads back the prefix at
discounted rates on every call after the first.

Streaming is used because per-call max_tokens=16000 can exceed default
non-streaming HTTP timeouts on slower endpoints.
"""

import json
import re
from typing import Any

from patent_agent.config import (
    DEFAULT_MODEL,
    PASS2_MAX_TOKENS,
    SVG_BYTE_LIMIT,
    SVG_PALETTE,
    SVG_VIEWBOX_H,
    SVG_VIEWBOX_W,
    SYSTEM_PROMPT_SVG,
)

_SVG_RE = re.compile(r"<svg\b[^>]*>.*?</svg>", re.DOTALL)


def _diagram_type_hint(diagram_type: str) -> str:
    hints = {
        "system_overview": "Spatial node graph. Place components in a clear hierarchy or radial layout. Use directional arrows for the most important interactions only — do not draw every edge. Aim for legibility over completeness.",
        "data_flow": "Left-to-right pipeline. Stages flow left to right; show what data transforms at each stage; label each arrow with the data type or signal.",
        "sequence": "Vertical lifelines for each component, time flowing top to bottom. Horizontal arrows between lifelines for messages. Number the messages 1, 2, 3 ... in sequence order.",
        "state_machine": "Circles for states, directed arrows for transitions, transition labels on arrows. Use a self-loop for stay-in-state behavior. Mark the initial state with a small filled dot and an arrow into it.",
        "topology": "Geometric layout (ring, star, mesh, bus) that reflects the physical or logical network topology. Show every node, but only the topology edges.",
    }
    return hints.get(diagram_type, "Use a layout appropriate to the components and interactions described.")


def build_svg_instruction(
    diagram: dict[str, Any],
    pass1_json: dict[str, Any],
) -> str:
    """Build the per-call instruction text."""

    compact_context = json.dumps(pass1_json, ensure_ascii=False, sort_keys=True)
    diagram_compact = json.dumps(diagram, ensure_ascii=False, sort_keys=True)
    palette_lines = "\n".join(
        f"  - {role}: {color}" for role, color in SVG_PALETTE.items()
    )

    return f"""Below is the structured understanding of the patent (Pass 1 output). Use it as the source of truth for component IDs, names, and interactions:

<patent_structure>
{compact_context}
</patent_structure>

Produce the following diagram now:

<diagram_to_draw>
{diagram_compact}
</diagram_to_draw>

Diagram-type guidance: {_diagram_type_hint(diagram["type"])}

Hard constraints for the SVG:

1. Root element: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_VIEWBOX_W} {SVG_VIEWBOX_H}" width="{SVG_VIEWBOX_W}" height="{SVG_VIEWBOX_H}">`.
2. Set background by drawing a `<rect>` covering the full viewBox with fill `{SVG_PALETTE["background"]}` as the first child.
3. Declare a `<defs>` block containing at least one arrowhead `<marker id="arrow">` (path d="M0,0 L10,5 L0,10 Z"). Use it via `marker-end="url(#arrow)"` on directional connectors.
4. Use semantic colors keyed off each component's `role`:
{palette_lines}
   Data-flow arrows themselves use stroke `{SVG_PALETTE["data_flow"]}`.
5. Stroke width: 2 for component outlines, 1.5 for connectors.
6. EVERY component node carries two lines of text:
   - English name (14px, font-weight 600, dark fill)
   - Simplified Chinese name (12px, regular weight, fill #555)
   Use a single `<text>` with two `<tspan>` children offset by `dy="1.4em"` for the second line. Center text inside the node.
7. EVERY connector carries its English label as a `<text>` on or near the line (12px). Add a `<title>` child element under the line/path containing the Chinese label — this becomes a hover tooltip without crowding the diagram.
8. Limit total SVG size to {SVG_BYTE_LIMIT} bytes. Prefer fewer, larger, labeled nodes over many small ones. Group secondary detail.
9. Only use components and interactions referenced by `focused_component_ids` and `focused_interaction_ids` in the diagram entry. If both arrays are empty, use your judgment based on the diagram `type` and `purpose`.

Output ONLY the SVG markup, starting with `<svg` and ending with `</svg>`. No Markdown fences. No commentary. No XML declaration."""


def _extract_svg(text: str) -> str | None:
    m = _SVG_RE.search(text)
    return m.group(0) if m else None


def _placeholder_svg(diagram_id: str, message: str) -> str:
    safe = (message or "").replace("<", "").replace(">", "")[:200]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200" width="800" height="200">'
        f'<rect width="800" height="200" fill="#FFF3E0" stroke="#FF6F00" stroke-width="2"/>'
        f'<text x="400" y="80" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#BF360C">'
        f'Diagram generation failed: {diagram_id}</text>'
        f'<text x="400" y="120" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#5D4037">'
        f'{safe}</text>'
        f'</svg>'
    )


def _convert_usage(usage_obj: Any) -> dict[str, int]:
    """OpenAI usage -> our internal usage dict."""
    if usage_obj is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    cached = 0
    details = getattr(usage_obj, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    prompt = getattr(usage_obj, "prompt_tokens", 0) or 0
    return {
        "input_tokens": prompt,
        "output_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
        "cache_creation_input_tokens": max(0, prompt - cached),
        "cache_read_input_tokens": cached,
    }


def _stream_one(
    client: Any,
    content_blocks: list[dict[str, Any]],
    model: str,
    instruction: str,
) -> tuple[str, dict[str, int]]:
    """Run one streamed Pass 2 call. Returns (raw_text, usage_dict).

    `content_blocks` is the prebuilt cached prefix (text + figure images
    already in OpenAI shape). It MUST be byte-identical to what Pass 1
    used so OpenAI's prompt cache hits."""

    user_content = list(content_blocks) + [{"type": "text", "text": instruction}]

    stream = client.chat.completions.create(
        model=model,
        max_tokens=PASS2_MAX_TOKENS,
        stream=True,
        stream_options={"include_usage": True},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_SVG},
            {"role": "user", "content": user_content},
        ],
    )

    chunks: list[str] = []
    final_usage: Any = None
    for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta and getattr(delta, "content", None):
                chunks.append(delta.content)
        if getattr(chunk, "usage", None):
            final_usage = chunk.usage

    return "".join(chunks), _convert_usage(final_usage)


def run_pass2_one(
    client: Any,
    content_blocks: list[dict[str, Any]],
    diagram: dict[str, Any],
    pass1_json: dict[str, Any],
    model: str = DEFAULT_MODEL,
) -> tuple[str, dict[str, int], bool]:
    """Generate one SVG diagram. Returns (svg_text, usage_dict, ok_flag)."""
    instruction = build_svg_instruction(diagram, pass1_json)
    text, usage = _stream_one(client, content_blocks, model, instruction)
    svg = _extract_svg(text)
    if svg:
        return svg, usage, True

    # Retry once with stricter instruction.
    retry_instruction = (
        instruction
        + "\n\nIMPORTANT: Your previous response did not contain parseable SVG. "
        "Output ONLY the raw SVG markup. No Markdown code fences. No commentary. "
        "Begin with `<svg` and end with `</svg>`."
    )
    text2, usage2 = _stream_one(client, content_blocks, model, retry_instruction)
    svg2 = _extract_svg(text2)

    # Merge usage from both calls
    merged = {k: usage.get(k, 0) + usage2.get(k, 0) for k in usage}

    if svg2:
        return svg2, merged, True

    return _placeholder_svg(diagram["id"], "SVG parse failed after retry"), merged, False
