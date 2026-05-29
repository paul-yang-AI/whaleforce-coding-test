"""Tier0 segmenter: TOC anchors + regex fallback + section-name fallback."""

from __future__ import annotations

import re
import warnings
from enum import Enum

from bs4 import BeautifulSoup
from pydantic import BaseModel

warnings.filterwarnings("ignore", category=UserWarning, message=".*XML.*")

from task2_sec.pipeline.normalize import normalize

# Line-start item headers only (avoids inline "see Item 1 above").
# Longer ids first so "Item 10" is not captured as Item "1".
_ITEM_ID = r"10|11|12|13|14|15|16|1[ABC]|7A|9A|9B|2|3|4|5|6|7|8|9|1"
HEADER_RE = re.compile(
    rf"(?m)^\s*(?:ITEM|Item)\s+(?P<id>{_ITEM_ID})\s*[\.:\-\u2014]?\s*",
    re.IGNORECASE,
)

# Section name → Item ID mapping for filings without explicit "Item N" headers.
# Patterns require the section name to appear on its own line (standalone header).
_SECTION_NAME_MAP: list[tuple[str, str]] = [
    (r"\n\s*Business\s*\n", "1"),
    (r"\n\s*Risk\s+Factors\s*\n", "1A"),
    (r"\n\s*Unresolved\s+Staff\s+Comments\s*\n", "1B"),
    (r"\n\s*Cybersecurity\s*\n", "1C"),
    (r"\n\s*Properties\s*\n", "2"),
    (r"\n\s*Legal\s+Proceedings\s*\n", "3"),
    (r"\n\s*Mine\s+Safety\s+Disclosures?\s*\n", "4"),
    (r"\n\s*Management.s\s+Discussion\s+and\s+Analysis\b[^\n]*\n", "7"),
    (r"\n\s*Quantitative\s+and\s+Qualitative\s+Disclosures?\s+About\s+Market\s+Risk\s*\n", "7A"),
    (r"\n\s*Market\s+Risk\s*\n\s*Overview\b", "7A"),
    (r"\n\s*Financial\s+Statements\s+and\s+Supplementary\s+Data\s*\n", "8"),
    (r"\n\s*Report\s+of\s+Independent\s+Registered\s+Public\s+Accounting\s+Firm\b[^\n]*\n", "8"),
    (r"\n\s*Changes\s+in\s+and\s+Disagreements\s+[Ww]ith\s+Accountants\b[^\n]*\n", "9"),
    (r"\n\s*Controls\s+and\s+Procedures\s*\n", "9A"),
    (r"\n\s*Directors[,\s]+Executive\s+Officers\b[^\n]*\n", "10"),
    (r"\n\s*Executive\s+Compensation\s*\n", "11"),
    (r"\n\s*Security\s+Ownership\b[^\n]*\n", "12"),
    (r"\n\s*Certain\s+Relationships\s+and\s+Related\s+Transactions\b[^\n]*\n", "13"),
    (r"\n\s*Principal\s+Account(?:ant|ing)\s+Fees\b[^\n]*\n", "14"),
    (r"\n\s*Exhibits?\s+and\s+Financial\s+Statement\s+Schedules?\b[^\n]*\n", "15"),
    (r"\n\s*Form\s+10-K\s+Summary\s*\n", "16"),
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
_SHORT_SEGMENT_CHARS = 300
_TOC_CLUSTER_GAP = 8000


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
        if pos - prev < _TOC_CLUSTER_GAP:
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
    if len(merged) >= 2:
        covered = sum(s.end - s.start for s in merged[:-1])
    else:
        covered = 0
    coverage_ratio = covered / body_len
    short_ratio = sum(1 for s in merged if (s.end - s.start) < _SHORT_SEGMENT_CHARS) / len(merged)
    return coverage_ratio, short_ratio


def _needs_section_name_fallback(merged: list[SegmentResult], body_len: int) -> bool:
    coverage_ratio, short_ratio = _coverage_metrics(merged, body_len)
    return len(merged) < 3 or coverage_ratio < 0.10 or short_ratio >= 0.35


def _scrub_toc_stub_segments(
    body: str,
    segments: list[SegmentResult],
    *,
    name_by_id: dict[str, SegmentResult] | None = None,
) -> list[SegmentResult]:
    """Drop short page-citation stubs when real section_name content exists later.

    Cross-reference-only items (e.g. INTC index rows with no in-document section)
    are kept so the UI can flag them as page-reference entries.
    """
    name_by_id = name_by_id or {}
    kept: list[SegmentResult] = []
    for seg in segments:
        text = body[seg.start : seg.end].strip()
        if len(text) >= _SHORT_SEGMENT_CHARS or not is_page_reference_text(text):
            kept.append(seg)
            continue
        alt = name_by_id.get(seg.item_id)
        if alt is None or alt.start <= seg.start:
            kept.append(seg)
            continue
    if len(kept) == len(segments):
        return segments
    kept = sorted(kept, key=lambda s: s.start)
    body_len = len(body)
    for i, seg in enumerate(kept):
        seg.end = kept[i + 1].start if i + 1 < len(kept) else body_len
    return kept


def assert_span_integrity(body: str, start: int, end: int, text: str) -> None:
    assert body[start:end] == text, f"span mismatch: {body[start:end]!r} != {text!r}"


def _normalize_item_id(raw: str) -> str:
    raw = raw.upper()
    if raw in {"1A", "1B", "1C", "7A", "9A", "9B"}:
        return raw
    return raw.lstrip("0") or raw


class Segmenter:
    def segment(
        self,
        html: str,
        *,
        run_id: str | None = None,
        use_llm_fallback: bool = True,
    ) -> tuple[str, list[SegmentResult]]:
        body = normalize(html)
        toc_hits = self._segment_from_toc(html, body)
        regex_hits = self._segment_from_regex(body)
        merged = self._merge_segments(toc_hits, regex_hits, len(body))

        if _needs_section_name_fallback(merged, len(body)):
            name_hits = self._segment_from_section_names(body)
            if name_hits:
                name_ids = {s.item_id for s in name_hits}
                supplementary = [s for s in merged if s.item_id not in name_ids]
                merged = self._merge_segments(name_hits, supplementary, len(body))

        merged = self._upgrade_short_segments(body, merged)
        name_hits_for_scrub = self._segment_from_section_names(body)
        name_by_id_scrub: dict[str, SegmentResult] = {}
        for hit in name_hits_for_scrub:
            prev = name_by_id_scrub.get(hit.item_id)
            if prev is None or hit.start > prev.start:
                name_by_id_scrub[hit.item_id] = hit
        merged = _scrub_toc_stub_segments(body, merged, name_by_id=name_by_id_scrub)
        merged = self._supplement_from_section_names(body, merged)

        found_ids = {s.item_id for s in merged}
        missing_count = sum(1 for iid in STANDARD_10K_ITEMS if iid not in found_ids)
        coverage_ratio, _ = _coverage_metrics(merged, len(body))
        needs_llm = use_llm_fallback and (missing_count > 5 or coverage_ratio < 0.30)

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
        self, body: str, segments: list[SegmentResult]
    ) -> list[SegmentResult]:
        """Replace TOC index stubs with later section_name hits when available."""
        name_hits = self._segment_from_section_names(body)
        name_by_id: dict[str, SegmentResult] = {}
        for hit in name_hits:
            prev = name_by_id.get(hit.item_id)
            if prev is None or hit.start > prev.start:
                name_by_id[hit.item_id] = hit

        upgraded = False
        for i, seg in enumerate(segments):
            text = body[seg.start : seg.end].strip()
            if len(text) >= _SHORT_SEGMENT_CHARS:
                continue
            alt = name_by_id.get(seg.item_id)
            if alt is None or alt.start <= seg.start:
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
        self, body: str, segments: list[SegmentResult]
    ) -> list[SegmentResult]:
        """Add section_name hits for items removed as TOC stubs or never found."""
        found = {s.item_id for s in segments}
        name_hits = self._segment_from_section_names(body)
        name_by_id: dict[str, SegmentResult] = {}
        for hit in name_hits:
            prev = name_by_id.get(hit.item_id)
            if prev is None or hit.start > prev.start:
                name_by_id[hit.item_id] = hit

        added = False
        for item_id, hit in name_by_id.items():
            if item_id not in found:
                segments.append(hit)
                added = True

        if not added:
            return segments
        segments = sorted(segments, key=lambda s: s.start)
        body_len = len(body)
        for i, seg in enumerate(segments):
            seg.end = segments[i + 1].start if i + 1 < len(segments) else body_len
        return segments

    def _segment_from_toc(self, html: str, body: str) -> list[SegmentResult]:
        """Discover item ids from TOC anchors; positions resolved via regex on body."""
        soup = BeautifulSoup(html, "lxml")
        item_ids: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not href.startswith("#"):
                continue
            anchor_id = href[1:]
            target = soup.find(id=anchor_id)
            if target is None:
                link_text = normalize(str(link))
                m = HEADER_RE.search(link_text.split("\n", 1)[0])
                if m:
                    item_ids.add(_normalize_item_id(m.group("id")))
                continue
            header_text = normalize(str(target)).split("\n", 1)[0].strip()
            m = HEADER_RE.search(header_text)
            if m:
                item_ids.add(_normalize_item_id(m.group("id")))

        results: list[SegmentResult] = []
        for item_id in sorted(item_ids, key=lambda x: self._find_content_header_start(body, x)):
            start = self._find_content_header_start(body, item_id)
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

    def _segment_from_regex(self, body: str) -> list[SegmentResult]:
        starts_by_id: dict[str, list[int]] = {}
        for m in HEADER_RE.finditer(body):
            item_id = _normalize_item_id(m.group("id"))
            starts_by_id.setdefault(item_id, []).append(m.start())

        hits: list[SegmentResult] = []
        for item_id, starts in starts_by_id.items():
            start = self._pick_best_start(starts, body)
            hits.append(
                SegmentResult(
                    item_id=item_id,
                    start=start,
                    end=start,
                    method=SegmentMethod.REGEX,
                )
            )
        return hits

    def _pick_best_start(self, starts: list[int], body: str) -> int:
        """Choose the best header position among multiple matches.

        Prefer occurrences outside dynamically detected TOC index zones; fall back
        to the legacy 5% margin heuristic for large filings.
        """
        if len(starts) == 1:
            return starts[0]

        toc_zones = _find_toc_zones(body)
        if toc_zones:
            outside = [s for s in starts if not _in_toc_zone(s, toc_zones)]
            if outside:
                return outside[0]

        body_len = len(body)
        if body_len > 20000:
            lo = body_len * 5 // 100
            hi = body_len - lo
            content_starts = [s for s in starts if lo < s < hi]
            if content_starts:
                return content_starts[0]

        return starts[-1]

    def _segment_from_section_names(self, body: str) -> list[SegmentResult]:
        """Fallback: detect sections by their standard 10-K section titles."""
        toc_zones = _find_toc_zones(body)
        if toc_zones and toc_zones[0][0] == 0:
            content_start = toc_zones[0][1]
        else:
            content_start = len(body) // 100
        hits: list[SegmentResult] = []
        for pattern_str, item_id in _SECTION_NAME_MAP:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            matches = list(pattern.finditer(body))
            if not matches:
                continue
            content_matches = [
                m
                for m in matches
                if m.start() > content_start and not _in_toc_zone(m.start(), toc_zones)
            ]
            if content_matches:
                best = content_matches[0]
            else:
                outside = [m for m in matches if not _in_toc_zone(m.start(), toc_zones)]
                if not outside:
                    continue
                best = outside[-1]

            hits.append(
                SegmentResult(
                    item_id=item_id,
                    start=best.start(),
                    end=best.start(),
                    method=SegmentMethod.SECTION_NAME,
                )
            )
        return hits

    def _find_content_header_start(self, body: str, item_id: str) -> int:
        starts = [
            m.start()
            for m in HEADER_RE.finditer(body)
            if _normalize_item_id(m.group("id")) == item_id
        ]
        if not starts:
            return -1
        return self._pick_best_start(starts, body)

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
        chunk_size = 8000
        hits: list[SegmentResult] = []

        for chunk_start in range(0, len(body), chunk_size):
            chunk_end = min(chunk_start + chunk_size, len(body))
            chunk = body[chunk_start:chunk_end]

            still_missing = [iid for iid in missing_ids if iid not in {h.item_id for h in hits}]
            if not still_missing:
                break

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
                    continue

                raw_clean = raw.strip()
                if raw_clean.startswith("```"):
                    raw_clean = re.sub(r"^```\w*\n?", "", raw_clean)
                    raw_clean = re.sub(r"\n?```$", "", raw_clean)

                items_found = _json.loads(raw_clean)
                if not isinstance(items_found, list):
                    continue

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
            except BudgetExceededError as exc:
                # Per-filing LLM budget is exhausted; further chunks would only
                # raise again before any network call. Stop scanning the rest of
                # the (potentially very long) body instead of spinning to the end.
                logger.warning("LLM segment fallback stopped at chunk %d: %s", chunk_start, exc)
                break
            except (AllProvidersFailed, Exception) as exc:
                logger.warning("LLM segment fallback failed for chunk %d: %s", chunk_start, exc)
                continue

        return hits
