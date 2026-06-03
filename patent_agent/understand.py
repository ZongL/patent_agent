"""Pass 1 - Patent understanding.

One API call. Produces a JSON object matching schema.PATENT_SCHEMA.

OpenAI Chat Completions; structured output via
`response_format = {"type": "json_schema", "json_schema": {..., "strict": True}}`.

Cache strategy (OpenAI prompt cache, automatic):
- System prompt is a constant from config.SYSTEM_PROMPT_UNDERSTAND.
- user message content[0..N-1] is the pre-built OpenAI-shaped block list
  from pdf_input.build_content_blocks (text + figure image_url).
- Companion HTML (if any) goes AFTER the stable prefix - only present in
  Pass 1, never in Pass 2, so Pass 2 cache hits still work.
- The instruction text always comes last.
"""

import json
import sys
import warnings
from typing import Any, Optional

from patent_agent.config import (
    DEFAULT_MODEL,
    PASS1_MAX_TOKENS,
    SYSTEM_PROMPT_UNDERSTAND,
    USER_INSTRUCTION_UNDERSTAND,
)
from patent_agent.schema import PATENT_SCHEMA


def _extract_usage(usage_obj: Any) -> dict[str, int]:
    """OpenAI usage -> the dict shape the rest of the code expects."""
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
        # OpenAI doesn't surface a separate cache_creation counter; treat
        # the non-cached fraction of the prompt as creation so totals add up.
        "cache_creation_input_tokens": max(0, prompt - cached),
        "cache_read_input_tokens": cached,
    }


# ---------------------------------------------------------------------------
# Post-parse normalisation
# ---------------------------------------------------------------------------
# Some model endpoints do not enforce strict JSON schema, so the LLM may
# return nested dicts or use different key names.  This function coerces
# every observed variant into the flat format defined by PATENT_SCHEMA.
#
# Called once right after json.loads() in run_pass1(), and once when loading
# a cached understanding.json in cli.py.

# Accepted alias keys (checked in order) for each bilingual scalar field.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title":      ("en", "zh", "en_US", "zh_CN"),
    "abstract":   ("en", "zh", "en_US", "zh_CN", "summary_en", "summary_zh"),
    "background": ("en", "zh", "en_US", "zh_CN", "summary_en", "summary_zh"),
}


def _pick_bilingual(val: dict[str, Any], aliases: tuple[str, ...]) -> tuple[str, str]:
    """Extract (en, zh) values from a dict using any of the alias keys."""
    en_val, zh_val = "", ""
    for a in aliases:
        if a not in val:
            continue
        if a.endswith("_en") or a in ("en", "en_US"):
            en_val = val[a]
        elif a.endswith("_zh") or a in ("zh", "zh_CN"):
            zh_val = val[a]
    return en_val, zh_val


def normalize_understanding(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce LLM output into the flat-key format of PATENT_SCHEMA.

    Operates in-place and returns *data*.  Never raises — if the LLM
    returned an unexpected shape we log a warning and return *data* as-is.
    """
    if not isinstance(data, dict):
        print(f"WARNING: normalize_understanding: expected dict, got {type(data).__name__}", file=sys.stderr)
        return data

    try:
        # -- patent_metadata wrapper (may hold title_en/zh) --------------------
        meta = data.get("patent_metadata")
        if isinstance(meta, dict):
            for key in ("title_en", "title_zh"):
                if key not in data and key in meta:
                    data[key] = meta[key]

        # -- bilingual scalar fields: title / abstract / background ------------
        for field, aliases in _FIELD_ALIASES.items():
            en_key = f"{field}_en"
            zh_key = f"{field}_zh"
            val = data.get(field)
            if isinstance(val, dict):
                en_val, zh_val = _pick_bilingual(val, aliases)
                data.setdefault(en_key, en_val)
                data.setdefault(zh_key, zh_val)
            elif isinstance(val, str) and en_key not in data:
                data[en_key] = val

        # -- key_claims → claim_text_en / claim_text_zh -------------------------
        _CLAIM_EN_ALIASES = ("claim_text_en", "rephrased_en", "description_en")
        _CLAIM_ZH_ALIASES = ("claim_text_zh", "rephrased_zh", "description_zh")
        for claim in (data.get("key_claims") or []):
            if not isinstance(claim, dict):
                continue
            if "claim_text_en" not in claim:
                for alias in _CLAIM_EN_ALIASES:
                    if alias in claim and alias != "claim_text_en":
                        claim["claim_text_en"] = claim.pop(alias)
                        break
            if "claim_text_zh" not in claim:
                for alias in _CLAIM_ZH_ALIASES:
                    if alias in claim and alias != "claim_text_zh":
                        claim["claim_text_zh"] = claim.pop(alias)
                        break

        # -- novel_aspects → aspect_en / aspect_zh ------------------------------
        _ASPECT_EN_ALIASES = ("aspect_en", "description_en", "en")
        _ASPECT_ZH_ALIASES = ("aspect_zh", "description_zh", "zh")
        for aspect in (data.get("novel_aspects") or []):
            if not isinstance(aspect, dict):
                continue
            # "aspect" (bare string, no _en suffix) → aspect_en
            if "aspect_en" not in aspect and isinstance(aspect.get("aspect"), str):
                aspect["aspect_en"] = aspect.pop("aspect")
            if "aspect_en" not in aspect:
                for alias in _ASPECT_EN_ALIASES:
                    if alias in aspect and alias != "aspect_en":
                        aspect["aspect_en"] = aspect.pop(alias)
                        break
            if "aspect_zh" not in aspect:
                for alias in _ASPECT_ZH_ALIASES:
                    if alias in aspect and alias != "aspect_zh":
                        aspect["aspect_zh"] = aspect.pop(alias)
                        break
    except Exception as exc:
        print(f"WARNING: normalize_understanding failed: {exc}", file=sys.stderr)

    return data


def run_pass1(
    client: Any,
    content_blocks: list[dict[str, Any]],
    companion_html: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Run the understanding pass. Returns (parsed_data, usage_dict)."""

    user_content: list[dict[str, Any]] = list(content_blocks)

    if companion_html:
        if len(companion_html) > 50_000:
            companion_html = companion_html[:50_000] + "\n[...truncated]"
        user_content.append({
            "type": "text",
            "text": (
                "Companion HTML (raw USPTO source -- use for cross-checking "
                "inventor names, applicant, patent number, and publication "
                "date; do not let the HTML override the PDF for technical "
                "content):\n\n"
                + companion_html
            ),
        })

    user_content.append({"type": "text", "text": USER_INSTRUCTION_UNDERSTAND})

    response = client.chat.completions.create(
        model=model,
        max_tokens=PASS1_MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_UNDERSTAND},
            {"role": "user", "content": user_content},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "patent_understanding",
                "schema": PATENT_SCHEMA,
                "strict": True,
            },
        },
    )

    text = response.choices[0].message.content
    if not text:
        raise RuntimeError(
            "Pass 1: empty completion content. The model returned no text - "
            "check that the endpoint supports strict json_schema response_format."
        )
    data = json.loads(text)
    normalize_understanding(data)  # enforce flat-key format in-place

    return data, _extract_usage(response.usage)
