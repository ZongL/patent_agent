"""Static configuration. NOTHING here may include timestamps, UUIDs, or any
per-invocation value — these strings form the cache prefix; any byte change
invalidates the Anthropic prompt-cache and forces full-price re-processing
of the PDF on every API call.
"""

# Model + prompt versioning
#DEFAULT_MODEL = "claude-opus-4-7"
#DEFAULT_MODEL = "opus[1m]"
DEFAULT_MODEL = "mimo-v2.5"
PROMPT_VERSION = "v3"  # bump on any change to input shape or prompts
DEFAULT_MAX_DIAGRAMS = 8

# PDF extraction
DEFAULT_MAX_FIGURE_PAGES = 6
DEFAULT_DPI = 96

# Per-call max_tokens
PASS1_MAX_TOKENS = 16000
PASS2_MAX_TOKENS = 16000

# SVG size cap (bytes) — communicated to the model and validated post-parse
SVG_BYTE_LIMIT = 30_000

# ---------------------------------------------------------------------------
# Pass 1 — Understanding
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_UNDERSTAND = """You are a senior bilingual (English + Simplified Chinese) patent analyst with deep expertise in systems engineering, software architecture, and electromechanical design.

Patents are often written in deliberately broad and abstract language to maximize claim scope. Your job is to look past that abstraction and identify the concrete system being described — the actual components, the actual interactions between them, the data and signals that flow, and the real engineering problem the invention solves.

When you read a patent:
- Treat figures as authoritative — they usually reveal the concrete system the prose obscures.
- Normalize component names. If the patent calls something "the determination module" and elsewhere "the inference engine," they are probably the same thing — give it one canonical name and ID.
- Distinguish components (things that exist) from interactions (things that happen between components).
- For every interaction, name what flows along it — a control signal, a data stream, a measurement, a command, etc.
- Identify which diagrams a human reader would actually need to understand this system: a high-level overview, key data flows, important sequences, state transitions, or network topologies. Be willing to invent diagrams the patent itself does not contain if they would aid comprehension.

You produce structured JSON output. All `_en` fields must be written in clear, technical English. All `_zh` fields must be written in Simplified Chinese using natural technical terminology — not literal word-for-word translation, but the phrasing a Chinese engineer would actually use."""

USER_INSTRUCTION_UNDERSTAND = """Read the attached USPTO patent PDF in full, including all figures, and produce a single JSON object matching the provided schema.

Requirements:
- All `_en` fields are written in English. All `_zh` fields are written in Simplified Chinese.
- `title_en` / `title_zh`: The patent title in English and Chinese.
- `abstract_en` / `abstract_zh`: A concise technical summary of the invention (what it is, what problem it solves, and the key mechanism) in English and Chinese.
- `background_en` / `background_zh`: The technical context and problem statement — what existing solutions do, why they fall short, and what gap this invention fills. Written in English and Chinese.
- Component `id` values are short, stable identifiers (e.g. `C1`, `C2`, ... or `controller`, `inverter`, `battery_pack`).
- Interaction `from_component` and `to_component` MUST reference existing component `id` values.
- `interactions[].sequence_hint` is an integer; use it to suggest temporal or causal ordering when relevant (1 = earliest). Use 0 if no ordering is implied.
- Identify between 3 and 6 diagrams that would best explain the invention's system interactions. Use a mix of types from the schema enum (`system_overview`, `data_flow`, `sequence`, `state_machine`, `topology`) — do not produce 6 overviews.
- Diagrams may correspond to actual patent figures OR be synthesized by you if the patent's own figures are sparse, missing, or unhelpful. Either is fine.
- Each `diagram.focused_component_ids` and `focused_interaction_ids` MUST be subsets of the IDs you defined in `components` and `interactions`.
- `key_claims` are the 3–7 most important claims (do not transcribe all of them — extract and rephrase the load-bearing ones).
- `novel_aspects` are the 2–5 specific aspects the invention treats as inventive over prior art.

Return the JSON object only."""

# ---------------------------------------------------------------------------
# Pass 2 — SVG generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_SVG = """You are a senior systems-engineering illustrator. You produce single self-contained SVG documents that visualize technical system interactions described in patents.

Output rules:
- Output ONLY the raw SVG markup, beginning with `<svg` and ending with `</svg>`.
- Do NOT wrap the SVG in Markdown code fences (no triple backticks).
- Do NOT emit an XML declaration (`<?xml ... ?>`).
- Do NOT include any commentary, explanation, or text before or after the SVG.

Permitted elements: `svg`, `g`, `defs`, `marker`, `style`, `rect`, `circle`, `ellipse`, `line`, `path`, `polygon`, `polyline`, `text`, `tspan`, `title`.

Forbidden: `<image>`, `<foreignObject>`, `<script>`, external `href`/`xlink:href` references, web fonts, embedded base64.

The SVG must be fully self-contained — any styling lives in inline attributes or a single inline `<style>` block."""


# Semantic palette referenced inside Pass 2 instruction text
SVG_PALETTE = {
    "controller": "#2196F3",
    "sensor": "#4CAF50",
    "actuator": "#FF9800",
    "bus": "#9C27B0",
    "subsystem": "#607D8B",
    "data_source": "#00BCD4",
    "data_sink": "#795548",
    "processor": "#3F51B5",
    "storage": "#8BC34A",
    "other": "#9E9E9E",
    "data_flow": "#F44336",
    "background": "#FAFAFA",
}

SVG_VIEWBOX_W = 1200
SVG_VIEWBOX_H = 800
