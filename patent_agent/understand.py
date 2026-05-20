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

    return data, _extract_usage(response.usage)
