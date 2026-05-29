import pytest

from task2_sec.pipeline.segment import _is_page_reference_only, is_page_reference_text

# Real strings observed in INTC's cross-reference-format 10-K (0000050863-25-000009).
_INTC_ITEM1_INDEX = (
    "\nItem 1.\nBusiness:\n\nGeneral development of business\n Pages 3-4, 13\n\n"
    "Description of business\nPages 3-20, 45-47, 51, 68-72\n\n"
    "Available information\nPage 2\n\nItem 1A.\nRisk Factors\nPages 31-46\n\nItem 1B."
)
_INTC_ITEM8_INDEX = (
    "\nFinancial Statements and Supplementary Data\nPages 53-101\n\nItem 9."
)


@pytest.mark.unit
def test_multi_pageref_index_entry_is_flagged() -> None:
    # 195-char entry with 4 page citations but topic labels > 80 chars residual.
    # Stricter detectors miss it; this one must catch it.
    assert is_page_reference_text(_INTC_ITEM1_INDEX) is True


@pytest.mark.unit
def test_single_pageref_short_entry_is_flagged() -> None:
    assert is_page_reference_text(_INTC_ITEM8_INDEX) is True


@pytest.mark.unit
def test_none_item_is_not_a_cross_reference() -> None:
    # Genuine short "None" items carry no page citations -> must NOT be flagged.
    assert is_page_reference_text("\nMine Safety Disclosures\nNone\n\nPart II\n") is False
    assert is_page_reference_text("\nExecutive Compensation\n(a)\n\nItem 12.") is False


@pytest.mark.unit
def test_long_real_section_is_not_a_cross_reference() -> None:
    real = "Risk Factors. " + ("Our business faces material risks. " * 40)
    assert len(real) >= 500
    assert is_page_reference_text(real) is False


@pytest.mark.unit
def test_substantial_prose_with_single_page_mention_not_flagged() -> None:
    # A single incidental page mention inside substantial prose (residual > 80
    # chars) must not trip either the residual rule or the >=2-citation rule.
    text = (
        "We describe our manufacturing operations, supply chain, and global "
        "distribution network across multiple regions and segments in detail on "
        "page 5 of this annual report for the fiscal year."
    )
    assert is_page_reference_text(text) is False


@pytest.mark.unit
def test_citi_style_bare_page_range_index_is_flagged() -> None:
    text = (
        "\nItem 7A.\nQuantitative and Qualitative Disclosures About Market Risk\n"
        "70–129, 174–178, 198–238, 245–292\n"
    )
    assert is_page_reference_text(text) is True
    assert _is_page_reference_only(text) is True


@pytest.mark.unit
def test_empty_text_not_flagged() -> None:
    assert is_page_reference_text("") is False
    assert is_page_reference_text("   ") is False
