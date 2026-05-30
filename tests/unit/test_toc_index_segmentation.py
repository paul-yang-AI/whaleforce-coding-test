"""TOC index detection, bare page-range citations, and short-segment upgrades."""

import pytest

from task2_sec.pipeline.normalize import normalize
from task2_sec.pipeline.segment import (
    SegmentMethod,
    Segmenter,
    _find_toc_zones,
    _is_page_reference_only,
    _is_topic_page_index_block,
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
def test_topic_page_index_block_detects_bare_page_number_lists() -> None:
    index_block = (
        "\nRisk Factors\n\n31\n\nSales and Marketing\n\n45\n\n"
        "Quantitative and Qualitative Disclosures About Market Risk\n\n47\n"
    )
    assert _is_topic_page_index_block(index_block) is True
    prose = (
        "Risk Factors\nThe following summarizes the material factors that make "
        "an investment in our securities speculative or risky."
    )
    assert _is_topic_page_index_block(prose) is False


@pytest.mark.unit
def test_upgrade_cross_ref_stub_at_document_end_to_earlier_section_name() -> None:
    """Cross-reference index at EOF upgrades to earlier prose (bidirectional, generic HTML)."""
    html = """
    <html><body>
    <h2>Risk Factors</h2>
    <p>{}</p>
    <h2>Management's Discussion and Analysis of Financial Condition</h2>
    <p>{}</p>
    <h2>Report of Independent Registered Public Accounting Firm</h2>
    <p>{}</p>
    <div>
    Item 1. Business: Pages 3-4, 13
    Item 1A. Risk Factors Pages 31-46
    Item 7. MD&A Pages 47-52
    Item 8. Financial Statements and Supplementary Data Pages 53-101
    </div>
    </body></html>
    """.format(
        "Material risk disclosure prose. " * 80,
        "MD&A narrative with liquidity and capital resources. " * 80,
        "Auditor opinion and consolidated financial statements discussion. " * 80,
    )
    segmenter = Segmenter()
    body, segments = segmenter.segment(html, use_llm_fallback=False)
    seg_1a = next(s for s in segments if s.item_id == "1A")
    text_1a = body[seg_1a.start : seg_1a.end]
    assert "Pages 31-46" not in text_1a
    assert "Material risk disclosure" in text_1a
    seg_8 = next(s for s in segments if s.item_id == "8")
    text_8 = body[seg_8.start : seg_8.end]
    assert "Pages 53-101" not in text_8
    assert "Auditor opinion" in text_8 or "financial statements" in text_8.lower()


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


@pytest.mark.unit
def test_find_front_index_zone_detects_bank_mega_toc() -> None:
    from task2_sec.pipeline.segment import _find_front_index_zone

    head = (
        "Business\n4–32\n\n1A.\n\nRisk Factors\n50–64\n\n"
        "5.\n\nMarket for Registrant's Common Equity\n146–147\n\n"
        "6.\n\nReserved\n\n7.\n\nManagement's Discussion\n7–32\n"
    )
    zone = _find_front_index_zone(head + ("padding\n" * 200))
    assert zone is not None
    assert zone[0] == 0
    assert zone[1] < 8000


@pytest.mark.unit
def test_pick_best_start_prefers_prose_over_front_index() -> None:
    from task2_sec.pipeline.segment import Segmenter

    body = (
        "Item 1.\n\nBusiness.\n\n1\n\nOverview\n\n1\n\n"
        "Business segments\n\n"
        + ("padding\n" * 400)
        + "Item 1. Business.\n\nOverview\nReal business narrative about operations and segments.\n"
        + ("More prose about the company. " * 80)
        + "\nItem 1A. Risk Factors.\nThe following discussion sets forth material risks.\n"
        + ("Risk detail paragraph. " * 80)
    )
    segmenter = Segmenter()
    starts_by_id = {"1": [body.find("Item 1.\n"), body.find("Item 1. Business.")], "1A": []}
    for m in __import__("re").finditer(r"Item 1A", body):
        starts_by_id.setdefault("1A", []).append(m.start())
    pick = segmenter._pick_best_start(starts_by_id["1"], body)
    assert "Real business narrative" in body[pick : pick + 500]
    pick_1a = segmenter._pick_best_start(starts_by_id["1A"], body)
    assert "material risks" in body[pick_1a : pick_1a + 200]


@pytest.mark.unit
def test_note_cross_ref_supplements_item_3() -> None:
    from task2_sec.pipeline.validate import validate_segment

    html = """
    <html><body>
    <p>{}</p>
    <div>
    Legal Proceedings—See Note 30 to the Consolidated Financial Statements
    301–308
    </div>
    </body></html>
    """.format("filler " * 500)
    segmenter = Segmenter()
    body, segments = segmenter.segment(html, use_llm_fallback=False)
    assert any(s.item_id == "3" for s in segments)
    r = validate_segment(body, next(s for s in segments if s.item_id == "3"), use_arbiter=False)
    assert r.item_id == "3"
    assert "cross_ref_financial_note" in r.warnings


@pytest.mark.unit
def test_disclosure_controls_pattern_supplements_9a_when_item9_is_index() -> None:
    """Generic bank-style filing: Item 9 index row must not block real Item 9A prose."""
    html = """
    <html><body>
    <div>
    9.
    Changes in and Disagreements with Accountants
    Not Applicable
    9A.
    Controls and Procedures
    135–136
    9B.
    Other Information
    317
    </div>
    <p>{}</p>
    <h2>DISCLOSURE CONTROLS AND PROCEDURES</h2>
    <p>{}</p>
    <h2>OTHER INFORMATION</h2>
    <p>{}</p>
    </body></html>
    """.format(
        "filler " * 4000,
        "Management evaluated disclosure controls and procedures effectiveness. " * 40,
        "Insider trading policies govern officer transactions. " * 40,
    )
    segmenter = Segmenter()
    body, segments = segmenter.segment(html, use_llm_fallback=False)
    seg_9a = next(s for s in segments if s.item_id == "9A")
    text_9a = body[seg_9a.start : seg_9a.end]
    assert "135" not in text_9a or "evaluated disclosure controls" in text_9a
    seg_9b = next(s for s in segments if s.item_id == "9B")
    text_9b = body[seg_9b.start : seg_9b.end]
    assert "Insider trading policies" in text_9b

