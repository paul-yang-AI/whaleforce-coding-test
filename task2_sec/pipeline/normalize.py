"""Normalize 10-K HTML to a canonical plain-text body for char-offset segmentation."""

from __future__ import annotations

import re
import unicodedata
import warnings

from bs4 import BeautifulSoup, NavigableString, Tag

warnings.filterwarnings("ignore", category=UserWarning, message=".*XML.*")

_IX_TAG = re.compile(r"^ix:", re.I)
_IX_STRUCTURAL = re.compile(r"^ix:(header|hidden|references|resources)", re.I)
_BLOCK_TAGS = frozenset({
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "tr", "td", "th", "br", "table", "blockquote",
    "section", "article", "header", "footer",
})


def normalize(html: str) -> str:
    """Strip iXBRL noise, unwrap inline tags, unify whitespace."""
    soup = BeautifulSoup(html, "lxml")

    # Remove non-content elements
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    # Remove iXBRL structural/metadata elements (hidden XBRL facts, schemas, contexts)
    _remove_ixbrl_metadata(soup)

    # Remove display:none elements (often wrap XBRL header blocks)
    _remove_hidden_elements(soup)

    # Unwrap remaining ix: inline tags (these wrap visible content)
    _unwrap_ixbrl(soup)

    text = _render_text(soup.body or soup)
    text = text.replace("\xa0", " ")
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _remove_ixbrl_metadata(root: Tag) -> None:
    """Remove ix:header, ix:hidden, ix:references, ix:resources entirely."""
    for tag in list(root.find_all(True)):
        name = tag.name or ""
        if _IX_STRUCTURAL.match(name):
            tag.decompose()


def _remove_hidden_elements(root: Tag) -> None:
    """Remove elements with display:none (invisible XBRL containers)."""
    for tag in list(root.find_all(True)):
        if tag.attrs is None:
            continue
        style = tag.get("style", "")
        if isinstance(style, str) and re.search(r"display\s*:\s*none", style, re.I):
            tag.decompose()


def _unwrap_ixbrl(root: Tag) -> None:
    """Unwrap ix:nonNumeric, ix:nonFraction, etc. — these wrap visible text."""
    for tag in list(root.find_all(True)):
        name = tag.name or ""
        if _IX_TAG.match(name):
            tag.unwrap()


def _render_text(node: Tag) -> str:
    parts: list[str] = []

    def walk(el: Tag | NavigableString) -> None:
        if isinstance(el, NavigableString):
            parts.append(str(el))
            return
        name = (el.name or "").lower()
        if name == "br":
            parts.append("\n")
            return
        for child in el.children:
            walk(child)
        if name in _BLOCK_TAGS:
            parts.append("\n")

    walk(node)
    return "".join(parts)
