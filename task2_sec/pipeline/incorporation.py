"""Detect Items incorporated by reference (e.g. Citi Items 10–14)."""

from __future__ import annotations

import re

INCORPORATION_RE = re.compile(
    r"incorporated\s+by\s+reference(?:\s+to|\s+from|\s+in|\s+herein)?",
    re.IGNORECASE,
)

PROXY_REFERENCE_RE = re.compile(
    r"incorporated\s+by\s+reference\s+to\s+(?:the\s+)?(?:definitive\s+)?proxy\s+statement",
    re.IGNORECASE,
)

# Max length for incorporation detection — long sections mentioning
# "incorporated by reference" in passing are actual content, not references
_MAX_INCORPORATION_LENGTH = 500


def detect_incorporation(text: str) -> tuple[bool, str | None]:
    """
    Return (is_incorporated, note).
    Does not generate replacement body text.
    """
    if not text:
        return False, None

    stripped = text.strip()

    # Only check for explicit incorporation language in SHORT segments
    if len(stripped) < _MAX_INCORPORATION_LENGTH and INCORPORATION_RE.search(text):
        if PROXY_REFERENCE_RE.search(text):
            return True, "此項目引用自 Proxy Statement，未包含於本文正文"
        return True, "此項目標記為 incorporated by reference，未包含於本文正文"

    # Heuristic: very short segments (<200 chars) with asterisk footnotes
    # indicate TOC entries referencing proxy statement (e.g. Citi Items 10-14)
    # Format: "Section Title\nPageNumbers*\n\nNextItem."
    if len(stripped) < 200 and "*" in stripped:
        lines = [l.strip() for l in stripped.splitlines() if l.strip()]
        if lines and _is_reference_entry(lines):
            return True, "此項目以腳註/頁碼引用方式呈現（incorporated by reference）"

    return False, None


def _is_reference_entry(lines: list[str]) -> bool:
    """Check if lines represent a TOC-style incorporation reference."""
    for line in lines:
        # Allow: section titles, page numbers with asterisks, bare asterisks,
        # item numbers like "11.", "(a)", "Part IV"
        if re.match(
            r"^("
            r"[\w',\s\-\u2013\u2014\(\)\.]+|"  # Title text or item numbers
            r"[\d\-\u2013\u2014\s,]*\*+|"  # Page numbers with asterisks
            r"\*+|"  # Bare asterisks
            r"\(\w\)"  # (a) style references
            r")$",
            line,
        ):
            continue
        return False
    return True
