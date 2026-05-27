"""DOM / a11y tree serialization and truncation."""

from __future__ import annotations

import json


def compress_a11y(
    tree: str | list | dict,
    *,
    max_chars: int = 12000,
    focus_hint: str | None = None,
) -> str:
    """Compress an a11y tree representation to fit within a char budget.

    If tree is already a string, truncate directly.
    If it's a list/dict (structured a11y snapshot), serialize and truncate.
    focus_hint: keep nodes whose text contains this substring close to budget center.
    """
    if isinstance(tree, (list, dict)):
        text = json.dumps(tree, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(tree)

    if len(text) <= max_chars:
        return text

    if focus_hint:
        idx = text.find(focus_hint)
        if idx >= 0:
            half = max_chars // 2
            start = max(0, idx - half)
            end = min(len(text), start + max_chars)
            return text[start:end]

    return text[:max_chars]
