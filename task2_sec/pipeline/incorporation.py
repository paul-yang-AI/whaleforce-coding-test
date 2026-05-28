"""Detect Items incorporated by reference (e.g. Citi Items 10–14, INTC Items 10–14)."""

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

_FOOTNOTE_MARKER_RE = re.compile(r"\(\s*[a-e]\s*\)\s*$", re.MULTILINE)

_MAX_INCORPORATION_LENGTH = 500

_PAGE_REF_RE = re.compile(
    r"(?:Pages?|pp?\.?)\s*[\d\-–,\s]+", re.IGNORECASE
)


def detect_incorporation(text: str) -> tuple[bool, str | None]:
    """Return (is_incorporated, note). Does not generate replacement body text."""
    if not text:
        return False, None

    stripped = text.strip()

    if len(stripped) < _MAX_INCORPORATION_LENGTH and INCORPORATION_RE.search(text):
        if PROXY_REFERENCE_RE.search(text):
            return True, "Incorporated by reference from Proxy Statement"
        return True, "Incorporated by reference"

    if len(stripped) < 200 and "*" in stripped:
        lines = [l.strip() for l in stripped.splitlines() if l.strip()]
        if lines and _is_reference_entry(lines):
            return True, "Incorporated by reference (footnote/page reference)"

    # INTC-style: short segments ending with "(a)" footnote marker pointing to
    # Proxy Statement. These items have section title + "(a)" and nothing else.
    if len(stripped) < 300 and _FOOTNOTE_MARKER_RE.search(stripped):
        content = re.sub(r"Item\s+\d+[A-Z]?\.?", "", stripped)
        content = re.sub(r"\(\s*[a-e]\s*\)", "", content)
        content = re.sub(r"Part\s+[IV]+", "", content)
        content = _PAGE_REF_RE.sub("", content)
        content = re.sub(r"[:\.\s\n]+", "", content).strip()
        if len(content) < 100:
            return True, "Incorporated by reference (proxy statement footnote)"

    return False, None


def _is_reference_entry(lines: list[str]) -> bool:
    """Check if lines represent a TOC-style incorporation reference."""
    for line in lines:
        if re.match(
            r"^("
            r"[\w',\s\-\u2013\u2014\(\)\.]+|"
            r"[\d\-\u2013\u2014\s,]*\*+|"
            r"\*+|"
            r"\(\w\)"
            r")$",
            line,
        ):
            continue
        return False
    return True
