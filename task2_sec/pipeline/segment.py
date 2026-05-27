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
    (r"\n\s*Risk\s+Factors\s*\n", "1A"),
    (r"\n\s*Unresolved\s+Staff\s+Comments\s*\n", "1B"),
    (r"\n\s*Cybersecurity\s*\n", "1C"),
    (r"\n\s*Management.s\s+Discussion\s+and\s+Analysis\b[^\n]*\n", "7"),
    (r"\n\s*Quantitative\s+and\s+Qualitative\s+Disclosures?\s+About\s+Market\s+Risk\s*\n", "7A"),
    (r"\n\s*Financial\s+Statements\s+and\s+Supplementary\s+Data\s*\n", "8"),
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


class SegmentMethod(str, Enum):
    TOC = "toc"
    REGEX = "regex"
    SECTION_NAME = "section_name"


class SegmentResult(BaseModel):
    item_id: str
    start: int
    end: int
    method: SegmentMethod


def assert_span_integrity(body: str, start: int, end: int, text: str) -> None:
    assert body[start:end] == text, f"span mismatch: {body[start:end]!r} != {text!r}"


def _normalize_item_id(raw: str) -> str:
    raw = raw.upper()
    if raw in {"1A", "1B", "1C", "7A", "9A", "9B"}:
        return raw
    return raw.lstrip("0") or raw


class Segmenter:
    def segment(self, html: str) -> tuple[str, list[SegmentResult]]:
        body = normalize(html)
        toc_hits = self._segment_from_toc(html, body)
        regex_hits = self._segment_from_regex(body)
        merged = self._merge_segments(toc_hits, regex_hits, len(body))

        # Fallback: if coverage is too low, regex likely only found TOC entries
        coverage = sum(s.end - s.start for s in merged) if merged else 0
        coverage_ratio = coverage / max(len(body), 1)
        needs_fallback = len(merged) < 3 or coverage_ratio < 0.10

        if needs_fallback:
            name_hits = self._segment_from_section_names(body)
            if name_hits:
                # Section-name hits take priority, but keep regex hits for
                # items not found by section_name (e.g., "Item 1" in TOC)
                name_ids = {s.item_id for s in name_hits}
                supplementary = [s for s in merged if s.item_id not in name_ids]
                merged = self._merge_segments(name_hits, supplementary, len(body))

        return body, merged

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

        body_len = len(body)
        hits: list[SegmentResult] = []
        for item_id, starts in starts_by_id.items():
            start = self._pick_best_start(starts, body_len)
            hits.append(
                SegmentResult(
                    item_id=item_id,
                    start=start,
                    end=start,
                    method=SegmentMethod.REGEX,
                )
            )
        return hits

    def _pick_best_start(self, starts: list[int], body_len: int) -> int:
        """Choose the best header position among multiple matches.

        For large documents: avoids TOC/index entries at the very start/end.
        For small docs or when all matches are in content area: take the last match
        (which is typically the content header, not the TOC entry).
        """
        if len(starts) == 1:
            return starts[0]

        # For large docs (>50K): exclude matches in first/last 3% (likely TOC/index)
        if body_len > 50000:
            lo = body_len * 3 // 100
            hi = body_len - lo
            content_starts = [s for s in starts if lo < s < hi]
            if content_starts:
                return content_starts[-1]

        # Default: take last match (content header after TOC entry)
        return starts[-1]

    def _segment_from_section_names(self, body: str) -> list[SegmentResult]:
        """Fallback: detect sections by their standard 10-K section titles."""
        hits: list[SegmentResult] = []
        for pattern_str, item_id in _SECTION_NAME_MAP:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            matches = list(pattern.finditer(body))
            if not matches:
                continue
            # Use the LAST match if multiple (first is often TOC reference)
            # But for large filings, prefer first match in the content area (>10% into doc)
            content_start = len(body) // 10
            content_matches = [m for m in matches if m.start() > content_start]
            if content_matches:
                best = content_matches[0]
            else:
                best = matches[-1]

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
        return starts[-1] if len(starts) > 1 else starts[0]

    def _merge_segments(
        self,
        toc: list[SegmentResult],
        regex: list[SegmentResult],
        body_len: int,
    ) -> list[SegmentResult]:
        by_id: dict[str, SegmentResult] = {}
        for seg in sorted(toc + regex, key=lambda s: (s.start, s.item_id)):
            existing = by_id.get(seg.item_id)
            if existing is None:
                by_id[seg.item_id] = seg
                continue
            if seg.method == SegmentMethod.REGEX and existing.method != SegmentMethod.REGEX:
                by_id[seg.item_id] = seg
            elif seg.method == existing.method and seg.start > existing.start:
                by_id[seg.item_id] = seg

        ordered = sorted(by_id.values(), key=lambda s: s.start)
        for i, seg in enumerate(ordered):
            end = ordered[i + 1].start if i + 1 < len(ordered) else body_len
            seg.end = end
        return ordered
