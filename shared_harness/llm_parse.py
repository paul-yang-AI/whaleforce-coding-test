"""Cross-provider JSON normalization and Pydantic parsing."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def parse_json_text(raw: str) -> str:
    """Strip markdown fences and whitespace from LLM JSON output."""
    t = raw.strip()
    if t.startswith("```"):
        t = t.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    # If there's surrounding text around the JSON object, extract it
    if not t.startswith("{"):
        m = _JSON_BLOCK_RE.search(t)
        if m:
            t = m.group(0)
    return t


def parse_model(raw: str, schema: type[T]) -> T:
    """Parse LLM output into a Pydantic model with progressive fallback."""
    cleaned = parse_json_text(raw)
    try:
        return schema.model_validate_json(cleaned)
    except (ValidationError, json.JSONDecodeError):
        pass

    # Fallback: try fixing common LLM issues (trailing commas, single quotes)
    fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return schema.model_validate_json(fixed)
    except (ValidationError, json.JSONDecodeError):
        pass

    # Last resort: parse as Python dict (handles single quotes, True/False)
    try:
        obj = json.loads(fixed)
    except json.JSONDecodeError:
        try:
            import ast
            obj = ast.literal_eval(fixed)
        except (ValueError, SyntaxError):
            # Re-raise original error for clarity
            return schema.model_validate_json(cleaned)
    return schema.model_validate(obj)
