"""L3 SEC manifest eval — train split, cache-only, zero LLM."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from shared_harness.eval_runner import load_manifest, run_sec_eval
from shared_harness.schemas.sec_schema import ItemStatus, STANDARD_ITEMS

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "task2_sec" / "eval" / "manifest.json"


@pytest.mark.eval
def test_sec_manifest_train_split() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    train = [f for f in manifest["filings"] if f.get("split") == "train"]
    assert len(train) >= 3

    with patch("shared_harness.llm_router.litellm.completion") as mock_completion:
        results = run_sec_eval(split="train", manifest_path=MANIFEST_PATH, use_arbiter=False)
        mock_completion.assert_not_called()

    assert len(results) == len(train)
    for result in results:
        assert result.required_items_found == result.required_items_total
        assert result.failure_category == "ok"
        if result.gold_items_total:
            assert result.gold_items_matched == result.gold_items_total
        assert result.token_ratio_p50 >= 0.85


@pytest.mark.eval
def test_sec_manifest_all_standard_items_present() -> None:
    from task2_sec.pipeline.fetch import fetch_filing_html
    from task2_sec.pipeline.run import extract_from_html

    manifest = load_manifest(MANIFEST_PATH)
    msft = next(f for f in manifest["filings"] if f["ticker"] == "MSFT")
    html, _, _ = fetch_filing_html(msft["accession"])
    extraction = extract_from_html(html, accession=msft["accession"], use_arbiter=False, use_llm_fallback=False)

    assert len(extraction.items) == len(STANDARD_ITEMS)
    item1 = next(i for i in extraction.items if i.item_id == "1")
    assert item1.status == ItemStatus.EXTRACTED
    assert item1.text and "Microsoft" in item1.text


@pytest.mark.eval
def test_sec_manifest_citi_incorporation() -> None:
    from task2_sec.pipeline.fetch import fetch_filing_html
    from task2_sec.pipeline.run import extract_from_html

    manifest = load_manifest(MANIFEST_PATH)
    citi = next(f for f in manifest["filings"] if f["ticker"] == "C")
    html, _, _ = fetch_filing_html(citi["accession"])
    extraction = extract_from_html(
        html, accession=citi["accession"], use_arbiter=False, use_llm_fallback=False
    )

    item10 = next(i for i in extraction.items if i.item_id == "10")
    item14 = next(i for i in extraction.items if i.item_id == "14")
    assert item10.status == ItemStatus.INCORPORATED_BY_REFERENCE
    assert item14.status == ItemStatus.INCORPORATED_BY_REFERENCE
    assert item10.text is None
    assert item14.text is None


@pytest.mark.eval
def test_run_eval_csv_at_least_three_rows(tmp_path: Path) -> None:
    import csv

    from shared_harness.eval_runner import run_eval

    csv_path = Path(run_eval(split="train", output_dir=str(tmp_path)))
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    sec_rows = [r for r in rows if r["task"] == "sec_10k"]
    assert len(sec_rows) >= 3
    assert "failure_category" in rows[0]
    assert "required_items_found" in rows[0]
    assert "required_prose_count" in rows[0]
    assert "expected_missing_ok_count" in rows[0]

    for row in sec_rows:
        assert row["failure_category"] == "ok"
        assert int(row.get("toc_stub_count") or 0) == 0
