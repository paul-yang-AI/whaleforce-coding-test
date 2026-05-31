"""Tier0 segmenter: TOC anchors + regex fallback + section-name fallback."""

from __future__ import annotations

import re
import warnings
from enum import Enum

from bs4 import BeautifulSoup
from pydantic import BaseModel

warnings.filterwarnings("ignore", category=UserWarning, message=".*XML.*")

from task2_sec.pipeline.normalize import normalize
from task2_sec.pipeline.incorporation import detect_incorporation
from task2_sec.pipeline.item_heuristics import detect_note_cross_reference

# Line-start item headers only (avoids inline "see Item 1 above").
# Longer ids first so "Item 10" is not captured as Item "1".
_ITEM_ID = r"10|11|12|13|14|15|16|1[ABC]|7A|9A|9B|2|3|4|5|6|7|8|9|1"
HEADER_RE = re.compile(
    rf"(?m)^\s*(?:ITEM|Item)\s+(?P<id>{_ITEM_ID})\s*[\.:\-\u2014]?\s*",
    re.IGNORECASE,
)

# Patterns require section titles on their own line (start of body or after newline).
_LINE = r"(?:^|\n)"
_SECTION_NAME_MAP: list[tuple[str, str]] = [
    # Cross-reference 10-Ks often use SEC-standard Business subheadings instead of "Item 1".
    (_LINE + r"\s*General\s+[Dd]evelopment\s+of\s+[Bb]usiness\s*\n", "1"),
    (_LINE + r"\s*Business\.?\s*\n", "1"),
    (_LINE + r"\s*Risk\s+Factors\.?\s*\n", "1A"),
    (_LINE + r"\s*Unresolved\s+Staff\s+Comments\s*\n", "1B"),
    (_LINE + r"\s*Cybersecurity\s*\n", "1C"),
    (_LINE + r"\s*Properties\s*\n", "2"),
    (_LINE + r"\s*Legal\s+Proceedings\s*\n", "3"),
    (_LINE + r"\s*Mine\s+Safety\s+Disclosures?\s*\n", "4"),
    (_LINE + r"\s*Market\s+for\s+Registrant.s\s+Common\s+Equity\b[^\n]*\n", "5"),
    (_LINE + r"\s*Management.s\s+Discussion\s+and\s+Analysis\b[^\n]*\n", "7"),
    (_LINE + r"\s*Quantitative\s+and\s+Qualitative\s+Disclosures?\s+About\s+Market\s+Risk\s*\n", "7A"),
    (_LINE + r"\s*Market\s+Risk\s*\n\s*Overview\b", "7A"),
    (_LINE + r"\s*Financial\s+Statements\s+and\s+Supplementary\s+Data\s*\n", "8"),
    (_LINE + r"\s*Report\s+of\s+Independent\s+Registered\s+Public\s+Accounting\s+Firm\b[^\n]*\n", "8"),
    (_LINE + r"\s*Changes\s+in\s+and\s+Disagreements\s+[Ww]ith\s+Accountants\b[^\n]*\n", "9"),
    # Banks often title Item 9A "Disclosure Controls and Procedures" (not bare "Controls…").
    (_LINE + r"\s*Disclosure\s+Controls\s+and\s+Procedures\s*\n", "9A"),
    (_LINE + r"\s*Controls\s+and\s+Procedures\s*\n", "9A"),
    (_LINE + r"\s*Other\s+Information\s*\n", "9B"),
    (_LINE + r"\s*Directors[,\s]+Executive\s+Officers\b[^\n]*\n", "10"),
    (_LINE + r"\s*Executive\s+Compensation\s*\n", "11"),
    (_LINE + r"\s*Security\s+Ownership\b[^\n]*\n", "12"),
    (_LINE + r"\s*Certain\s+Relationships\s+and\s+Related\s+Transactions\b[^\n]*\n", "13"),
    (_LINE + r"\s*Principal\s+Account(?:ant|ing)\s+Fees\b[^\n]*\n", "14"),
    (_LINE + r"\s*Exhibits?\s+and\s+Financial\s+Statement\s+Schedules?\b[^\n]*\n", "15"),
    (_LINE + r"\s*Form\s+10-K\s+Summary\s*\n", "16"),
]

_SECTION_NAME_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern_str, re.IGNORECASE), item_id)
    for pattern_str, item_id in _SECTION_NAME_MAP
]


STANDARD_10K_ITEMS = [
    "1", "1A", "1B", "1C", "2", "3", "4",
    "5", "6", "7", "7A", "8",
    "9", "9A", "9B",
    "10", "11", "12", "13", "14", "15", "16",
]

# Explicit "Pages 3-4" style OR bare ranges like "70–129, 174–178" (common in bank TOC).
_PAGE_REF_RE = re.compile(
    r"(?:"
    r"(?:Pages?|pp?\.?)\s*[\d\-–,\s]+"
    r"|"
    r"\d+\s*[–\-]\s*\d+(?:\s*,\s*\d+\s*[–\-]\s*\d+)*"
    r")",
    re.IGNORECASE,
)
_ITEM_LINE_RE = re.compile(r"Item\s+\d+[A-Z]?\.", re.IGNORECASE)
_ITEM_INDEX_LINE_RE = re.compile(
    r"(?m)^[^\n]*(?:ITEM|Item)\s+\d+[A-Z]?[\.\:\-\u2014]?"
    r"[^\n]*(?:"
    r"(?:Pages?|pp?\.?)\s*[\d\-–,\s]+"
    r"|\d+\s*[–\-]\s*\d+(?:\s*,\s*\d+\s*[–\-]\s*\d+)*"
    r")",
    re.IGNORECASE,
)
# Bank mega-TOC rows: "5.\n\nMarket for…\n146–147" without "Item" on the same line.
_ITEM_DOT_LINE_RE = re.compile(r"(?m)^\s*\d+[A-Z]?\.\s*$")
_PAGE_RANGE_LINE_RE = re.compile(
    r"(?m)^\s*\d+\s*[–\-]\s*\d+(?:\s*,\s*\d+\s*[–\-]\s*\d+)*\s*$"
)
_INCORPORATION_PREVIEW_CHARS = 200
_EOF_CLUSTER_FRAC = 0.85
# Item 3 often points to a financial statement note instead of standalone prose.
_NOTE_XREF_SEGMENT_RES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"(?:^|\n)\s*Legal\s+Proceedings[^\n]{0,140}"
            r"See\s+Note\s+\d+\s+to\s+the\s+Consolidated\s+Financial\s+Statements[^\n]*",
            re.IGNORECASE,
        ),
        "3",
    ),
]
_SHORT_SEGMENT_CHARS = 300  # default; use _scale_short_segment_chars(body_len)
_TOC_CLUSTER_GAP = 8000
# Section titles that often appear in tables/TOC — require a unique content-zone match.
_UNIQUE_CONTENT_ITEMS = frozenset({"7A", "8"})


def _scale_short_segment_chars(body_len: int) -> int:
    return max(200, min(500, body_len // 4000))


def _scale_toc_cluster_gap(body_len: int) -> int:
    return max(4000, min(12000, body_len // 120))


def _scale_short_ratio_threshold(body_len: int) -> float:
    return 0.35 if body_len > 400_000 else 0.40


def _content_start_for_names(body_len: int, toc_zones: list[tuple[int, int]]) -> int:
    if toc_zones and toc_zones[0][0] == 0:
        return min(toc_zones[0][1], max(5000, body_len // 20))
    return max(5000, body_len // 100)


def _strip_page_citation_text(text: str) -> str:
    content = _PAGE_REF_RE.sub("", text)
    content = _ITEM_LINE_RE.sub("", content)
    content = re.sub(r"Part\s+[IV]+", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\(\s*[a-e]\s*\)", "", content)
    return re.sub(r"[:\.\s\n\r,;]+", "", content).strip()


def _find_toc_zones(body: str, *, min_lines: int = 3) -> list[tuple[int, int]]:
    """Locate TOC index blocks by density of Item-header lines with page citations."""
    index_positions = [m.start() for m in _ITEM_INDEX_LINE_RE.finditer(body)]
    body_len = len(body)
    if len(index_positions) < min_lines:
        return []

    zones: list[tuple[int, int]] = []
    cluster_start = index_positions[0]
    prev = index_positions[0]
    cluster_size = 1

    for pos in index_positions[1:]:
        gap = _scale_toc_cluster_gap(body_len)
        if pos - prev < gap:
            cluster_size += 1
            prev = pos
            continue
        if cluster_size >= min_lines:
            zones.append((cluster_start, min(body_len, prev + 500)))
        cluster_start = pos
        prev = pos
        cluster_size = 1

    if cluster_size >= min_lines:
        zones.append((cluster_start, min(body_len, prev + 500)))
    return zones


def _in_toc_zone(pos: int, zones: list[tuple[int, int]]) -> bool:
    return any(lo <= pos < hi for lo, hi in zones)


def _find_front_index_zone(body: str) -> tuple[int, int] | None:
    """Detect bank-style front mega-TOC (numbered rows + bare page ranges, no 'Item' prefix)."""
    body_len = len(body)
    scan = min(body_len, 6500)
    if scan < 800:
        return None
    head = body[:scan]
    item_dots = len(_ITEM_DOT_LINE_RE.findall(head))
    page_ranges = len(_PAGE_RANGE_LINE_RE.findall(head))
    if item_dots < 4 or page_ranges < 4:
        return None
    dot_ends = [m.end() for m in _ITEM_DOT_LINE_RE.finditer(head)]
    if not dot_ends:
        return None
    cluster_end = min(body_len, max(dot_ends) + 200)
    return (0, cluster_end)


def _scrub_toc_zones(body: str) -> list[tuple[int, int]]:
    """TOC zones for index-stub removal (front mega-TOC + Item-line clusters)."""
    zones = _find_toc_zones(body)
    front = _find_front_index_zone(body)
    if front is None:
        return zones
    if zones and zones[0][0] == 0:
        return [(0, max(zones[0][1], front[1]))] + zones[1:]
    return [front] + zones


def _effective_toc_zones(body: str) -> list[tuple[int, int]]:
    """Alias for scrub/supplement stub detection."""
    return _scrub_toc_zones(body)


def _is_incorporation_index_stub(body: str, seg: SegmentResult) -> bool:
    """Part III index rows with * / ** footnotes — keep for incorporation detection."""
    text = body[seg.start : seg.end]
    incorporated, _ = detect_incorporation(text)
    return incorporated


def _is_eof_index_cluster(body: str, pos: int) -> bool:
    return pos >= len(body) * _EOF_CLUSTER_FRAC


def _is_mega_toc_segment(text: str) -> bool:
    """One segment spanning multiple numbered Item rows with page citations."""
    if len(text) > 2500:
        return False
    item_dots = len(_ITEM_DOT_LINE_RE.findall(text))
    if item_dots >= 3 and _PAGE_REF_RE.search(text):
        return True
    return item_dots >= 2 and len(_PAGE_REF_RE.findall(text)) >= 2


def _is_index_stub_segment(
    body: str,
    seg: SegmentResult,
    toc_zones: list[tuple[int, int]],
) -> bool:
    """True when a segment is a TOC/index row, not real section prose."""
    text = body[seg.start : seg.end].strip()
    short_limit = _scale_short_segment_chars(len(body))
    if _is_topic_page_index_block(text):
        return True
    if _is_mega_toc_segment(text):
        return True
    if len(text) < short_limit and is_page_reference_text(text):
        return True
    if (
        len(text) < 600
        and _ITEM_DOT_LINE_RE.search(text)
        and _PAGE_REF_RE.search(text)
        and len(_strip_page_citation_text(text)) < 120
    ):
        return True
    if _in_toc_zone(seg.start, toc_zones) and len(text) < short_limit:
        if is_page_reference_text(text) or _is_topic_page_index_block(text):
            return True
    return False


def _anchor_preview(body: str, start: int, *, window_chars: int = 600) -> str:
    return body[start : min(len(body), start + window_chars)].strip()


def _anchor_quality_key(
    body: str,
    start: int,
    toc_zones: list[tuple[int, int]],
) -> tuple[int, int, int]:
    """Sort key for section_name anchors — lower is better (real prose, outside TOC)."""
    window = _anchor_preview(body, start)
    indexish = 1 if _is_topic_page_index_block(window) else 0
    in_toc = 1 if _in_toc_zone(start, toc_zones) else 0
    return (indexish, in_toc, start)


def _best_section_name_by_id(
    body: str,
    name_hits: list[SegmentResult],
    toc_zones: list[tuple[int, int]],
) -> dict[str, SegmentResult]:
    """Pick the best prose anchor per item (not simply the last match in the document)."""
    by_id: dict[str, SegmentResult] = {}
    best_keys: dict[str, tuple[int, int, int]] = {}
    for hit in name_hits:
        key = _anchor_quality_key(body, hit.start, toc_zones)
        prev = best_keys.get(hit.item_id)
        if prev is None or key < prev:
            by_id[hit.item_id] = hit
            best_keys[hit.item_id] = key
    return by_id


def _is_usable_content_anchor(
    body: str,
    anchor: SegmentResult,
    toc_zones: list[tuple[int, int]],
) -> bool:
    """True when a section_name hit looks like real prose, not another index row."""
    preview = _anchor_preview(body, anchor.start, window_chars=220)
    if _is_topic_page_index_block(preview):
        return False
    if is_page_reference_text(preview) or _is_mega_toc_segment(preview):
        return False
    if _anchor_quality_key(body, anchor.start, toc_zones)[0] == 1:
        return False
    return True


_TOPIC_INDEX_LINE_RE = re.compile(r"^\d{1,3}$")


def _is_topic_page_index_block(text: str, *, max_chars: int = 900) -> bool:
    """Detect topic + bare page-number index blocks (cross-ref filings without 'Pages' keyword)."""
    clean = text.strip()
    if not clean or len(clean) > max_chars:
        return False
    if is_page_reference_text(clean):
        return True
    if len(clean) < 500 and _PAGE_REF_RE.search(clean):
        if len(_strip_page_citation_text(clean)) < 80:
            return True
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    if len(lines) >= 2:
        second = lines[1]
        if re.match(r"^\d{1,3}\s*[–\-]\s*\d{1,3}$", second) or _TOPIC_INDEX_LINE_RE.match(second):
            return True
    if len(lines) < 4:
        return False
    digit_lines = sum(1 for ln in lines if _TOPIC_INDEX_LINE_RE.match(ln))
    if digit_lines < 2:
        return False
    short_lines = sum(
        1 for ln in lines if len(ln) < 55 and not ln.endswith(".") and len(ln.split()) < 8
    )
    return short_lines >= 3


def _is_page_reference_only(text: str) -> bool:
    """Detect if text is just a cross-reference index entry (page numbers only)."""
    if len(text) > 500:
        return False
    return len(_strip_page_citation_text(text)) < 80


def is_page_reference_text(text: str) -> bool:
    """Presentation helper: is an extracted item really a cross-reference index?

    Some filings (e.g. cross-reference-format 10-Ks) map each SEC Item to page
    numbers in an index table — e.g. "Item 1. Business: ... Pages 3-4, 13 ...".
    Such an entry is short and dominated by page citations even when it carries
    a few topic labels (so the stricter ``_is_page_reference_only`` misses it).

    Signals (no filing-specific strings, so this generalizes):
      - short text (< 500 chars) AND
      - contains page citations, AND
      - either the non-citation residual is tiny, or there are >= 2 citations.

    Genuine short items such as "None" / "Not applicable" carry no page
    citations and are therefore never flagged.
    """
    clean = text.strip()
    if not clean or len(clean) >= 500:
        return False
    page_refs = _PAGE_REF_RE.findall(clean)
    if not page_refs:
        return False
    if _is_page_reference_only(clean):
        return True
    return len(page_refs) >= 2


def _header_start_quality_key(
    body: str,
    pos: int,
    toc_zones: list[tuple[int, int]],
) -> tuple[int, int, int]:
    """Sort key for regex/TOC header picks — prefer prose over index rows."""
    preview = _anchor_preview(body, pos, window_chars=220)
    indexish = 1 if (
        _is_topic_page_index_block(preview)
        or is_page_reference_text(preview)
        or _is_mega_toc_segment(preview)
    ) else 0
    in_toc = 1 if _in_toc_zone(pos, toc_zones) else 0
    # Among equal quality, prefer later match (legacy starts[-1] for small docs).
    return (indexish, in_toc, -pos)


def _supplement_note_cross_ref_items(
    body: str,
    segments: list[SegmentResult],
    toc_zones: list[tuple[int, int]],
) -> list[SegmentResult]:
    """Add short note-pointer rows (e.g. Item 3 → See Note N) when no header segment exists."""
    found = {s.item_id for s in segments}
    added = False
    for pattern, item_id in _NOTE_XREF_SEGMENT_RES:
        if item_id in found:
            continue
        for match in pattern.finditer(body):
            snippet = body[match.start() : match.start() + 400]
            if not detect_note_cross_reference(snippet)[0]:
                continue
            segments.append(
                SegmentResult(
                    item_id=item_id,
                    start=match.start(),
                    end=match.start(),
                    method=SegmentMethod.SECTION_NAME,
                )
            )
            added = True
            break
    if not added:
        return segments
    segments = sorted(segments, key=lambda s: s.start)
    body_len = len(body)
    for i, seg in enumerate(segments):
        seg.end = segments[i + 1].start if i + 1 < len(segments) else body_len
    return segments


class SegmentMethod(str, Enum):
    TOC = "toc"
    REGEX = "regex"
    SECTION_NAME = "section_name"
    LLM = "llm"


class SegmentResult(BaseModel):
    item_id: str
    start: int
    end: int
    method: SegmentMethod


def _coverage_metrics(merged: list[SegmentResult], body_len: int) -> tuple[float, float]:
    """Return (coverage_ratio, short_segment_ratio) for fallback decisions."""
    if not merged or body_len <= 0:
        return 0.0, 1.0
    short_limit = _scale_short_segment_chars(body_len)
    if len(merged) >= 2:
        covered = sum(s.end - s.start for s in merged[:-1])
    else:
        covered = 0
    coverage_ratio = covered / body_len
    short_ratio = sum(1 for s in merged if (s.end - s.start) < short_limit) / len(merged)
    return coverage_ratio, short_ratio


def _needs_section_name_fallback(merged: list[SegmentResult], body_len: int) -> bool:
    coverage_ratio, short_ratio = _coverage_metrics(merged, body_len)
    return (
        len(merged) < 3
        or coverage_ratio < 0.10
        or short_ratio >= _scale_short_ratio_threshold(body_len)
    )


def _scrub_toc_stub_segments(
    body: str,
    segments: list[SegmentResult],
    *,
    name_by_id: dict[str, SegmentResult] | None = None,
    toc_zones: list[tuple[int, int]] | None = None,
) -> list[SegmentResult]:
    """Drop page-citation stubs when a usable section_name anchor exists.

    Bare bank-TOC rows (Citi-style) require a *later* anchor; cross-reference index
    rows (``Pages N`` style) may upgrade to an *earlier* prose anchor (bidirectional).
    """
    name_by_id = name_by_id or {}
    if toc_zones is None:
        toc_zones = _effective_toc_zones(body)
    short_limit = _scale_short_segment_chars(len(body))
    kept: list[SegmentResult] = []
    for seg in segments:
        text = body[seg.start : seg.end].strip()
        if len(text) >= short_limit or not is_page_reference_text(text):
            kept.append(seg)
            continue
        alt = name_by_id.get(seg.item_id)
        if alt is None or not _is_usable_content_anchor(body, alt, toc_zones):
            kept.append(seg)
            continue
        is_cross_ref = bool(re.search(r"\bPages?\s+\d", text, re.IGNORECASE))
        if alt.start == seg.start:
            if is_page_reference_text(text) or _is_topic_page_index_block(text):
                continue
            kept.append(seg)
            continue
        if is_cross_ref:
            continue
        if alt.start <= seg.start:
            kept.append(seg)
            continue
    if len(kept) == len(segments):
        return segments
    kept = sorted(kept, key=lambda s: s.start)
    body_len = len(body)
    for i, seg in enumerate(kept):
        seg.end = kept[i + 1].start if i + 1 < len(kept) else body_len
    return kept


def _scrub_index_stub_segments(
    body: str,
    segments: list[SegmentResult],
    *,
    name_by_id: dict[str, SegmentResult] | None = None,
    toc_zones: list[tuple[int, int]] | None = None,
) -> list[SegmentResult]:
    """Drop front/duplicate index stubs; keep EOF cross-ref rows when no prose anchor exists."""
    name_by_id = name_by_id or {}
    if toc_zones is None:
        toc_zones = _effective_toc_zones(body)
    front = _find_front_index_zone(body)

    def _in_front_zone(pos: int) -> bool:
        return front is not None and front[0] <= pos < front[1]

    kept: list[SegmentResult] = []
    for seg in segments:
        if _is_incorporation_index_stub(body, seg):
            kept.append(seg)
            continue
        if not _is_index_stub_segment(body, seg, toc_zones):
            kept.append(seg)
            continue
        alt = name_by_id.get(seg.item_id)
        has_usable_alt = (
            alt is not None
            and alt.start != seg.start
            and _is_usable_content_anchor(body, alt, toc_zones)
        )
        if has_usable_alt:
            continue
        if _in_front_zone(seg.start):
            continue
        if _is_eof_index_cluster(body, seg.start):
            kept.append(seg)
            continue
        if _in_toc_zone(seg.start, toc_zones):
            continue
        kept.append(seg)

    if len(kept) == len(segments):
        return segments
    kept = sorted(kept, key=lambda s: s.start)
    body_len = len(body)
    for i, seg in enumerate(kept):
        seg.end = kept[i + 1].start if i + 1 < len(kept) else body_len
    return kept


def _dedupe_segments_by_item(
    body: str,
    segments: list[SegmentResult],
    toc_zones: list[tuple[int, int]],
) -> list[SegmentResult]:
    """Keep one segment per item_id — best prose anchor wins."""
    best: dict[str, SegmentResult] = {}
    for seg in segments:
        prev = best.get(seg.item_id)
        if prev is None:
            best[seg.item_id] = seg
            continue
        if _anchor_quality_key(body, seg.start, toc_zones) < _anchor_quality_key(
            body, prev.start, toc_zones
        ):
            best[seg.item_id] = seg
    return sorted(best.values(), key=lambda s: s.start)


class SpanIntegrityError(ValueError):
    """Raised when extracted text does not match body[start:end] (zero-hallucination contract)."""


def assert_span_integrity(body: str, start: int, end: int, text: str) -> None:
    if body[start:end] != text:
        raise SpanIntegrityError(f"span mismatch: {body[start:end]!r} != {text!r}")


def _normalize_item_id(raw: str) -> str:
    raw = raw.upper()
    if raw in {"1A", "1B", "1C", "7A", "9A", "9B"}:
        return raw
    return raw.lstrip("0") or raw


_TOC_HTML_SCAN_CHARS = 900_000  # TOC lives in the document head; avoid parsing multi-MB HTML


class Segmenter:
    def segment(
        self,
        html: str,
        *,
        run_id: str | None = None,
        use_llm_fallback: bool = True,
    ) -> tuple[str, list[SegmentResult]]:
        body = normalize(html)
        toc_zones = _scrub_toc_zones(body)
        front_zone = _find_front_index_zone(body)
        starts_by_id: dict[str, list[int]] = {}
        for m in HEADER_RE.finditer(body):
            item_id = _normalize_item_id(m.group("id"))
            starts_by_id.setdefault(item_id, []).append(m.start())

        name_hits_cache: list[SegmentResult] | None = None

        def get_name_hits() -> list[SegmentResult]:
            nonlocal name_hits_cache
            if name_hits_cache is None:
                name_hits_cache = self._segment_from_section_names(
                    body, toc_zones=_find_toc_zones(body), front_zone=front_zone
                )
            return name_hits_cache

        def name_by_id_best() -> dict[str, SegmentResult]:
            return _best_section_name_by_id(body, get_name_hits(), toc_zones)

        toc_hits = self._segment_from_toc(
            html, body, toc_zones=toc_zones, starts_by_id=starts_by_id
        )
        regex_hits = self._segment_from_regex(
            body, toc_zones=toc_zones, starts_by_id=starts_by_id
        )
        merged = self._merge_segments(toc_hits, regex_hits, len(body))

        if _needs_section_name_fallback(merged, len(body)):
            name_hits = get_name_hits()
            if name_hits:
                name_ids = {s.item_id for s in name_hits}
                supplementary = [s for s in merged if s.item_id not in name_ids]
                merged = self._merge_segments(name_hits, supplementary, len(body))

        best_names = name_by_id_best()
        merged = self._upgrade_short_segments(
            body, merged, name_by_id=best_names, toc_zones=toc_zones
        )
        merged = _scrub_toc_stub_segments(
            body, merged, name_by_id=best_names, toc_zones=toc_zones
        )
        merged = _scrub_index_stub_segments(
            body, merged, name_by_id=best_names, toc_zones=toc_zones
        )
        merged = self._supplement_from_section_names(
            body, merged, name_by_id=best_names, toc_zones=toc_zones
        )
        merged = _dedupe_segments_by_item(body, merged, toc_zones)
        merged = _supplement_note_cross_ref_items(body, merged, toc_zones)
        merged = _dedupe_segments_by_item(body, merged, toc_zones)
        for i, seg in enumerate(merged):
            seg.end = merged[i + 1].start if i + 1 < len(merged) else len(body)

        found_ids = {s.item_id for s in merged}
        missing_count = sum(1 for iid in STANDARD_10K_ITEMS if iid not in found_ids)
        coverage_ratio, short_ratio = _coverage_metrics(merged, len(body))
        short_limit = _scale_short_segment_chars(len(body))
        toc_stub_count = sum(
            1
            for s in merged
            if is_page_reference_text(body[s.start : s.end].strip())
            and (s.end - s.start) < short_limit
        )
        needs_llm = use_llm_fallback and (
            missing_count > 5
            or coverage_ratio < 0.30
            or (short_ratio >= _scale_short_ratio_threshold(len(body)) and toc_stub_count >= 2)
        )

        if needs_llm:
            llm_hits = self._segment_from_llm(body, found_ids, run_id=run_id)
            if llm_hits:
                for lh in llm_hits:
                    if lh.item_id not in found_ids:
                        merged.append(lh)
                        found_ids.add(lh.item_id)
                merged = sorted(merged, key=lambda s: s.start)
                for i, seg in enumerate(merged):
                    seg.end = merged[i + 1].start if i + 1 < len(merged) else len(body)

        return body, merged

    def _upgrade_short_segments(
        self,
        body: str,
        segments: list[SegmentResult],
        *,
        name_by_id: dict[str, SegmentResult] | None = None,
        toc_zones: list[tuple[int, int]] | None = None,
    ) -> list[SegmentResult]:
        """Replace page-citation stubs with section_name prose anchors when available."""
        if toc_zones is None:
            toc_zones = _effective_toc_zones(body)
        if name_by_id is None:
            name_hits = self._segment_from_section_names(body, toc_zones=toc_zones)
            name_by_id = _best_section_name_by_id(body, name_hits, toc_zones)

        upgraded = False
        short_limit = _scale_short_segment_chars(len(body))
        for i, seg in enumerate(segments):
            text = body[seg.start : seg.end].strip()
            is_cross_ref = bool(re.search(r"\bPages?\s+\d", text, re.IGNORECASE))
            is_stub = len(text) < short_limit or is_page_reference_text(text)
            if not is_stub:
                continue
            alt = name_by_id.get(seg.item_id)
            if alt is None or not _is_usable_content_anchor(body, alt, toc_zones):
                continue
            if alt.start == seg.start:
                continue
            if is_cross_ref:
                replace = True
            else:
                replace = alt.start > seg.start
            if not replace:
                continue
            segments[i] = SegmentResult(
                item_id=seg.item_id,
                start=alt.start,
                end=alt.start,
                method=SegmentMethod.SECTION_NAME,
            )
            upgraded = True

        if upgraded:
            segments = sorted(segments, key=lambda s: s.start)
            for i, seg in enumerate(segments):
                seg.end = segments[i + 1].start if i + 1 < len(segments) else len(body)
        return segments

    def _supplement_from_section_names(
        self,
        body: str,
        segments: list[SegmentResult],
        *,
        name_by_id: dict[str, SegmentResult] | None = None,
        toc_zones: list[tuple[int, int]] | None = None,
    ) -> list[SegmentResult]:
        """Add section_name hits for items removed as TOC stubs or never found."""
        if toc_zones is None:
            toc_zones = _effective_toc_zones(body)
        if name_by_id is None:
            name_hits = self._segment_from_section_names(body, toc_zones=toc_zones)
            name_by_id = _best_section_name_by_id(body, name_hits, toc_zones)

        def _is_good(seg: SegmentResult) -> bool:
            return not _is_index_stub_segment(body, seg, toc_zones)

        def _keep_after_stub_scrub(seg: SegmentResult) -> bool:
            if _is_incorporation_index_stub(body, seg):
                return True
            if _is_good(seg):
                return True
            if _is_eof_index_cluster(body, seg.start):
                return True
            alt = name_by_id.get(seg.item_id)
            if (
                alt is not None
                and alt.start != seg.start
                and _is_usable_content_anchor(body, alt, toc_zones)
            ):
                return False
            return False

        found_good = {s.item_id for s in segments if _is_good(s)}
        original = list(segments)

        segments = [s for s in segments if _keep_after_stub_scrub(s)]

        added = False
        for item_id, hit in name_by_id.items():
            if item_id in found_good:
                continue
            if not _is_usable_content_anchor(body, hit, toc_zones):
                continue
            segments.append(hit)
            added = True

        if not added and segments == original:
            return segments
        segments = sorted(segments, key=lambda s: s.start)
        body_len = len(body)
        for i, seg in enumerate(segments):
            seg.end = segments[i + 1].start if i + 1 < len(segments) else body_len
        return segments

    def _segment_from_toc(
        self,
        html: str,
        body: str,
        *,
        toc_zones: list[tuple[int, int]] | None = None,
        starts_by_id: dict[str, list[int]] | None = None,
    ) -> list[SegmentResult]:
        """Discover item ids from TOC anchors; positions resolved via regex on body."""
        html_for_toc = (
            html
            if len(html) <= 2_000_000
            else html[:_TOC_HTML_SCAN_CHARS]
        )
        soup = BeautifulSoup(html_for_toc, "lxml")
        id_index = {
            tag.get("id"): tag
            for tag in soup.find_all(True, id=True)
            if tag.get("id")
        }
        item_ids: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not href.startswith("#"):
                continue
            anchor_id = href[1:]
            target = id_index.get(anchor_id)
            if target is None:
                link_text = link.get_text(" ", strip=True)
                m = HEADER_RE.search(link_text.split("\n", 1)[0])
                if m:
                    item_ids.add(_normalize_item_id(m.group("id")))
                continue
            header_text = target.get_text(" ", strip=True).split("\n", 1)[0].strip()
            m = HEADER_RE.search(header_text)
            if m:
                item_ids.add(_normalize_item_id(m.group("id")))

        if starts_by_id is None:
            starts_by_id = {}
            for m in HEADER_RE.finditer(body):
                item_id = _normalize_item_id(m.group("id"))
                starts_by_id.setdefault(item_id, []).append(m.start())

        results: list[SegmentResult] = []
        for item_id in sorted(item_ids, key=lambda x: self._header_start(body, x, starts_by_id, toc_zones)):
            start = self._header_start(body, item_id, starts_by_id, toc_zones)
            if start >= 0:
                results.append(
                    SegmentResult(
                        item_id=item_id,
                        start=start,
                        end=start,
                        method=SegmentMethod.TOC,
                    )
                )
        return results

    def _header_start(
        self,
        body: str,
        item_id: str,
        starts_by_id: dict[str, list[int]],
        toc_zones: list[tuple[int, int]] | None,
    ) -> int:
        starts = starts_by_id.get(item_id, [])
        if not starts:
            return -1
        return self._pick_best_start(starts, body, toc_zones=toc_zones)

    def _segment_from_regex(
        self,
        body: str,
        *,
        toc_zones: list[tuple[int, int]] | None = None,
        starts_by_id: dict[str, list[int]] | None = None,
    ) -> list[SegmentResult]:
        if starts_by_id is None:
            starts_by_id = {}
            for m in HEADER_RE.finditer(body):
                item_id = _normalize_item_id(m.group("id"))
                starts_by_id.setdefault(item_id, []).append(m.start())

        hits: list[SegmentResult] = []
        for item_id, starts in starts_by_id.items():
            start = self._pick_best_start(starts, body, toc_zones=toc_zones)
            hits.append(
                SegmentResult(
                    item_id=item_id,
                    start=start,
                    end=start,
                    method=SegmentMethod.REGEX,
                )
            )
        return hits

    def _pick_best_start(
        self,
        starts: list[int],
        body: str,
        *,
        toc_zones: list[tuple[int, int]] | None = None,
    ) -> int:
        """Choose the best header position among multiple matches.

        Prefer occurrences outside dynamically detected TOC index zones; fall back
        to the legacy 5% margin heuristic for large filings.
        """
        if len(starts) == 1:
            return starts[0]

        if toc_zones is None:
            toc_zones = _find_toc_zones(body)
        if toc_zones:
            outside = [s for s in starts if not _in_toc_zone(s, toc_zones)]
            if outside:
                return min(
                    outside,
                    key=lambda s: _header_start_quality_key(body, s, toc_zones),
                )

        body_len = len(body)
        if body_len > 20000:
            lo = body_len * 5 // 100
            hi = body_len - lo
            content_starts = [s for s in starts if lo < s < hi]
            if content_starts:
                return min(
                    content_starts,
                    key=lambda s: _header_start_quality_key(body, s, toc_zones),
                )

        return min(starts, key=lambda s: _header_start_quality_key(body, s, toc_zones))

    def _segment_from_section_names(
        self,
        body: str,
        *,
        toc_zones: list[tuple[int, int]] | None = None,
        front_zone: tuple[int, int] | None = None,
    ) -> list[SegmentResult]:
        """Fallback: detect sections by their standard 10-K section titles."""
        if toc_zones is None:
            toc_zones = _find_toc_zones(body)
        if front_zone is None:
            front_zone = _find_front_index_zone(body)
        toc_at_front = bool(front_zone and front_zone[0] == 0)
        content_start = (
            min(front_zone[1], max(5000, len(body) // 20))
            if front_zone
            else _content_start_for_names(len(body), toc_zones)
        )
        hits: list[SegmentResult] = []
        for pattern, item_id in _SECTION_NAME_PATTERNS:
            matches = list(pattern.finditer(body))
            if not matches:
                continue
            content_matches = [
                m
                for m in matches
                if not (
                    _in_toc_zone(m.start(), toc_zones)
                    and _is_topic_page_index_block(
                        _anchor_preview(body, m.start(), window_chars=220)
                    )
                )
                and (
                    not toc_at_front
                    or m.start() > content_start
                    or detect_incorporation(
                        body[m.start() : m.start() + _INCORPORATION_PREVIEW_CHARS]
                    )[0]
                )
            ]
            if not content_matches:
                outside = [m for m in matches if not _in_toc_zone(m.start(), toc_zones)]
                if not outside:
                    continue
                content_matches = outside

            prose_matches = [
                m
                for m in content_matches
                if detect_incorporation(
                    body[m.start() : m.start() + _INCORPORATION_PREVIEW_CHARS]
                )[0]
                or (
                    not _is_topic_page_index_block(
                        _anchor_preview(body, m.start(), window_chars=220)
                    )
                    and not is_page_reference_text(
                        _anchor_preview(body, m.start(), window_chars=220)
                    )
                )
            ]
            if not prose_matches:
                continue
            best_match = min(
                prose_matches,
                key=lambda m: _anchor_quality_key(body, m.start(), toc_zones),
            )
            hits.append(
                SegmentResult(
                    item_id=item_id,
                    start=best_match.start(),
                    end=best_match.start(),
                    method=SegmentMethod.SECTION_NAME,
                )
            )
        return hits

    def _find_content_header_start(
        self,
        body: str,
        item_id: str,
        *,
        starts_by_id: dict[str, list[int]] | None = None,
        toc_zones: list[tuple[int, int]] | None = None,
    ) -> int:
        if starts_by_id is None:
            starts = [
                m.start()
                for m in HEADER_RE.finditer(body)
                if _normalize_item_id(m.group("id")) == item_id
            ]
        else:
            starts = starts_by_id.get(item_id, [])
        if not starts:
            return -1
        return self._pick_best_start(starts, body, toc_zones=toc_zones)

    def _merge_segments(
        self,
        toc: list[SegmentResult],
        regex: list[SegmentResult],
        body_len: int,
    ) -> list[SegmentResult]:
        by_id: dict[str, SegmentResult] = {}
        # Regex hits processed first; TOC overwrites only if position is further
        for seg in regex:
            by_id[seg.item_id] = seg
        for seg in toc:
            existing = by_id.get(seg.item_id)
            if existing is None:
                by_id[seg.item_id] = seg
            elif seg.start > existing.start:
                by_id[seg.item_id] = seg

        ordered = sorted(by_id.values(), key=lambda s: s.start)
        for i, seg in enumerate(ordered):
            end = ordered[i + 1].start if i + 1 < len(ordered) else body_len
            seg.end = end
        return ordered

    def _segment_from_llm(
        self,
        body: str,
        already_found: set[str],
        *,
        run_id: str | None = None,
        max_split_depth: int = 2,
    ) -> list[SegmentResult]:
        """LLM fallback: ask the model to identify item boundaries in a text chunk.

        Only invoked when Tier0 methods found < 50% of standard items.
        The LLM returns character offsets — text is always body[start:end].
        """
        import json as _json
        import logging

        logger = logging.getLogger(__name__)

        try:
            from shared_harness.cost_tracker import BudgetExceededError
            from shared_harness.llm_router import AllProvidersFailed, complete
            from shared_harness.prompt_loader import load_prompt
        except ImportError:
            return []

        missing_ids = [iid for iid in STANDARD_10K_ITEMS if iid not in already_found]
        if not missing_ids:
            return []

        segment_template = load_prompt("sec_segment_fallback")
        hits: list[SegmentResult] = []

        def _parse_chunk(chunk_start: int, chunk_end: int, depth: int) -> bool:
            """Return True if chunk was processed without needing a split retry."""
            chunk = body[chunk_start:chunk_end]
            if len(chunk) < 400:
                return True

            still_missing = [iid for iid in missing_ids if iid not in {h.item_id for h in hits}]
            if not still_missing:
                return True

            prompt = segment_template.format(
                missing_items=", ".join("Item " + iid for iid in still_missing),
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                chunk_text=chunk,
            )

            try:
                raw = complete(
                    tier=1,
                    call_site="sec_llm_segment",
                    messages=[{"role": "user", "content": prompt}],
                    run_id=run_id,
                    task_type="filing",
                    max_tokens=1024,
                )
                if not isinstance(raw, str):
                    return False

                raw_clean = raw.strip()
                if raw_clean.startswith("```"):
                    raw_clean = re.sub(r"^```\w*\n?", "", raw_clean)
                    raw_clean = re.sub(r"\n?```$", "", raw_clean)

                items_found = _json.loads(raw_clean)
                if not isinstance(items_found, list):
                    return False

                for item in items_found:
                    iid = _normalize_item_id(str(item.get("item_id", "")))
                    offset = int(item.get("offset_in_chunk", -1))
                    if iid not in still_missing or offset < 0 or offset >= len(chunk):
                        continue
                    abs_start = chunk_start + offset
                    hits.append(
                        SegmentResult(
                            item_id=iid,
                            start=abs_start,
                            end=abs_start,
                            method=SegmentMethod.LLM,
                        )
                    )
                return True
            except BudgetExceededError as exc:
                logger.warning(
                    "LLM segment fallback stopped at chunk %d: %s", chunk_start, exc
                )
                raise
            except (AllProvidersFailed, Exception) as exc:
                logger.warning(
                    "LLM segment fallback failed for chunk %d (depth=%d): %s",
                    chunk_start,
                    depth,
                    exc,
                )
                if depth < max_split_depth and len(chunk) > 2000:
                    mid = chunk_start + len(chunk) // 2
                    _parse_chunk(chunk_start, mid, depth + 1)
                    _parse_chunk(mid, chunk_end, depth + 1)
                    return True
                return False

        chunk_size = 8000
        try:
            for chunk_start in range(0, len(body), chunk_size):
                chunk_end = min(chunk_start + chunk_size, len(body))
                if not _parse_chunk(chunk_start, chunk_end, depth=0):
                    continue
                if not [iid for iid in missing_ids if iid not in {h.item_id for h in hits}]:
                    break
        except BudgetExceededError:
            pass

        return hits
