"""JSON schema for Pass 1 structured output.

All objects set `additionalProperties: false` (required by Anthropic
structured-outputs). No `minItems`, `maxItems`, `minLength`, `minimum`,
`maximum` etc. — those constraints are not supported and the SDK will
strip them silently.
"""

PATENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title_en",
        "title_zh",
        "abstract_en",
        "abstract_zh",
        "background_en",
        "background_zh",
        "components",
        "interactions",
        "diagrams",
        "key_claims",
        "novel_aspects",
    ],
    "properties": {
        "title_en": {"type": "string"},
        "title_zh": {"type": "string"},
        "abstract_en": {"type": "string"},
        "abstract_zh": {"type": "string"},
        "background_en": {"type": "string"},
        "background_zh": {"type": "string"},
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "name_en",
                    "name_zh",
                    "description_en",
                    "description_zh",
                    "role",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "name_en": {"type": "string"},
                    "name_zh": {"type": "string"},
                    "description_en": {"type": "string"},
                    "description_zh": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": [
                            "controller",
                            "sensor",
                            "actuator",
                            "bus",
                            "subsystem",
                            "data_source",
                            "data_sink",
                            "processor",
                            "storage",
                            "other",
                        ],
                    },
                },
            },
        },
        "interactions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "from_component",
                    "to_component",
                    "label_en",
                    "label_zh",
                    "data_or_signal",
                    "sequence_hint",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "from_component": {"type": "string"},
                    "to_component": {"type": "string"},
                    "label_en": {"type": "string"},
                    "label_zh": {"type": "string"},
                    "data_or_signal": {"type": "string"},
                    "sequence_hint": {"type": "integer"},
                },
            },
        },
        "diagrams": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "title_en",
                    "title_zh",
                    "purpose_en",
                    "purpose_zh",
                    "type",
                    "focused_component_ids",
                    "focused_interaction_ids",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "title_en": {"type": "string"},
                    "title_zh": {"type": "string"},
                    "purpose_en": {"type": "string"},
                    "purpose_zh": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "system_overview",
                            "data_flow",
                            "sequence",
                            "state_machine",
                            "topology",
                        ],
                    },
                    "focused_component_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "focused_interaction_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "key_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim_text_en", "claim_text_zh", "importance"],
                "properties": {
                    "claim_text_en": {"type": "string"},
                    "claim_text_zh": {"type": "string"},
                    "importance": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
            },
        },
        "novel_aspects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["aspect_en", "aspect_zh"],
                "properties": {
                    "aspect_en": {"type": "string"},
                    "aspect_zh": {"type": "string"},
                },
            },
        },
    },
}
