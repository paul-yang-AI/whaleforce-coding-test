"""TOC index detection, bare page-range citations, and short-segment upgrades."""

import pytest

from task2_sec.pipeline.normalize import normalize
from task2_sec.pipeline.segment import (
    SegmentMethod,
    Segmenter,
    _find_toc_zones,
    _is_page_reference_only,
    _needs_section_name_fallback,
    is_page_reference_text,
)
from task2_sec.pipeline.segment import SegmentResult

# Citi-style bare page ranges (no "Pages" keyword).
_CITI_7A_INDEX = (
    "\nItem 7A.\nQuantitative and Qualitative Disclosures About Market Risk\n"
    "70–129, 174–178, 198–238, 245–292\n"
)


@pytest.mark.unit
def test_bare_page_range_index_is_flagged() -> None:
    assert is_page_reference_text(_CITI_7A_INDEX) is True
    assert _is_page_reference_only(_CITI_7A_INDEX) is True


@pytest.mark.unit
def test_find_toc_zones_clusters_dense_index_block() -> None:
    toc = (
        "Item 1. Business 1-5\n"
        "Item 1A. Risk Factors 10-50\n"
        "Item 7A. Market Risk 70-129, 174-178\n"
        "Item 8. Financial Statements 130-200\n"
    )
    body = toc + ("filler line\n" * 200) + "Item 7. MD&A\nReal content section\n"
    zones = _find_toc_zones(body, min_lines=3)
    assert zones
    assert zones[0][0] == 0
    assert any(z[1] > 100 for z in zones)


@pytest.mark.unit
def test_needs_section_name_fallback_when_many_short_segments() -> None:
    body_len = 100_000
    merged = [
        SegmentResult(item_id="1", start=100, end=200, method=SegmentMethod.REGEX),
        SegmentResult(item_id="1A", start=200, end=300, method=SegmentMethod.REGEX),
        SegmentResult(item_id="7", start=300, end=400, method=SegmentMethod.REGEX),
        SegmentResult(item_id="7A", start=400, end=500, method=SegmentMethod.REGEX),
        SegmentResult(item_id="8", start=500, end=body_len, method=SegmentMethod.REGEX),
    ]
    assert _needs_section_name_fallback(merged, body_len) is True


@pytest.mark.unit
def test_upgrade_short_toc_stub_to_later_section_name() -> None:
    html = """
    <html><body>
    <div>
    Item 7A. Quantitative and Qualitative Disclosures About Market Risk 70-129, 174-178
    Item 8. Financial Statements and Supplementary Data 130-200
    </div>
    <p>{}</p>
    <h2>Quantitative and Qualitative Disclosures About Market Risk</h2>
    <p>Real market risk narrative with interest rate and FX exposure details.</p>
    <h2>Financial Statements and Supplementary Data</h2>
    <p>Consolidated balance sheets and statements of income for the fiscal year.</p>
    </body></html>
    """.format("padding " * 3000)
    segmenter = Segmenter()
    body, segments = segmenter.segment(html, use_llm_fallback=False)
    seg_7a = next(s for s in segments if s.item_id == "7A")
    text_7a = body[seg_7a.start : seg_7a.end]
    assert "70-129" not in text_7a or "interest rate" in text_7a
    assert "Real market risk" in text_7a or seg_7a.method == SegmentMethod.SECTION_NAME


@pytest.mark.unit
def test_pick_best_start_skips_toc_when_content_header_exists() -> None:
    html = """
    <html><body>
    <div>
    Item 10. Directors 50-60
    Item 11. Executive Compensation 61-70
    Item 12. Security Ownership 71-80
    </div>
    <p>{}</p>
    <h2>Item 10. Directors, Executive Officers and Corporate Governance</h2>
    <p>Director biographies and committee charters are described herein.</p>
    </body></html>
    """.format("x " * 5000)
    segmenter = Segmenter()
    body, segments = segmenter.segment(html, use_llm_fallback=False)
    seg_10 = next(s for s in segments if s.item_id == "10")
    text = body[seg_10.start : seg_10.end]
    assert "Director biographies" in text
    assert "50-60" not in text[:120]
