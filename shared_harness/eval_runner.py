"""SEC manifest eval — load filings, score pipeline, export CSV."""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared_harness.schemas.sec_schema import ItemStatus
from task2_sec.pipeline.fetch import fetch_filing_html
from task2_sec.pipeline.metrics import token_ratio
from task2_sec.pipeline.run import extract_from_html

_EVAL_ROOT = Path(__file__).resolve().parent.parent / "task2_sec" / "eval"
DEFAULT_MANIFEST = _EVAL_ROOT / "manifest.json"
DEFAULT_GOLD_DIR = _EVAL_ROOT / "gold"


@dataclass
class FilingEvalResult:
    accession: str
    ticker: str | None
    cik: str | None
    split: str
    required_items_found: int
    required_items_total: int
    gold_boundary_errors: list[int] = field(default_factory=list)
    gold_items_matched: int = 0
    gold_items_total: int = 0
    toc_header_agreement: float = 0.0
    token_ratio_p50: float = 0.0
    char_coverage: float = 0.0
    tier0_extracted_count: int = 0
    incorporated_count: int = 0
    missing_count: int = 0
    low_confidence_count: int = 0
    usd_per_filing: float = 0.0
    fallback_used: bool = False
    failure_category: str = "ok"

    def to_csv_row(self) -> dict[str, Any]:
        gold_p95 = max(self.gold_boundary_errors) if self.gold_boundary_errors else 0
        return {
            "task": "sec_10k",
            "accession": self.accession,
            "ticker": self.ticker or "",
            "cik": self.cik or "",
            "split": self.split,
            "required_items_found": self.required_items_found,
            "required_items_total": self.required_items_total,
            "gold_items_matched": self.gold_items_matched,
            "gold_items_total": self.gold_items_total,
            "gold_boundary_p95": gold_p95,
            "toc_header_agreement": round(self.toc_header_agreement, 4),
            "token_ratio_p50": round(self.token_ratio_p50, 4),
            "char_coverage": round(self.char_coverage, 4),
            "tier0_extracted_count": self.tier0_extracted_count,
            "incorporated_count": self.incorporated_count,
            "missing_count": self.missing_count,
            "low_confidence_count": self.low_confidence_count,
            "usd_per_filing": round(self.usd_per_filing, 6),
            "fallback_used": self.fallback_used,
            "failure_category": self.failure_category,
        }


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or DEFAULT_MANIFEST
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _load_gold(accession: str, gold_dir: Path | None = None) -> dict[str, Any] | None:
    gold_path = (gold_dir or DEFAULT_GOLD_DIR) / f"{accession}.json"
    if not gold_path.exists():
        return None
    return json.loads(gold_path.read_text(encoding="utf-8"))


def _item_satisfied(status: ItemStatus) -> bool:
    return status in {
        ItemStatus.EXTRACTED,
        ItemStatus.INCORPORATED_BY_REFERENCE,
        ItemStatus.LOW_CONFIDENCE,
        ItemStatus.NOT_APPLICABLE,
    }


def _classify_failure(
    *,
    required_found: int,
    required_total: int,
    gold_matched: int,
    gold_total: int,
    low_confidence_count: int,
    gold_errors: list[int],
) -> str:
    if required_found < required_total:
        return "missing_item_header"
    if gold_total and gold_matched < gold_total:
        if any(e > 50 for e in gold_errors):
            return "arbiter_boundary_error"
        return "span_integrity_fail"
    if low_confidence_count > 0:
        return "low_confidence"
    return "ok"


def evaluate_filing(
    filing: dict[str, Any],
    *,
    gold_dir: Path | None = None,
    use_arbiter: bool = False,
    run_id: str | None = None,
    required_items: list[str] | None = None,
) -> FilingEvalResult:
    accession = filing["accession"]
    html = fetch_filing_html(accession)
    extraction = extract_from_html(
        html,
        accession=accession,
        cik=filing.get("cik"),
        ticker=filing.get("ticker"),
        run_id=run_id,
        use_arbiter=use_arbiter,
    )

    required = filing.get("required_items") or required_items or ["1", "1A", "7", "8"]
    by_id = {item.item_id: item for item in extraction.items}
    required_found = sum(
        1 for item_id in required if item_id in by_id and _item_satisfied(by_id[item_id].status)
    )

    gold = _load_gold(accession, gold_dir)
    gold_items = (gold or {}).get("items", {})
    gold_errors: list[int] = []
    gold_matched = 0
    for item_id, expected in gold_items.items():
        actual = by_id.get(item_id)
        if actual is None or actual.start is None or actual.end is None:
            continue
        if actual.status.value != expected.get("status", actual.status.value):
            continue
        start_err = abs(actual.start - int(expected["start"]))
        end_err = abs(actual.end - int(expected["end"]))
        gold_errors.extend([start_err, end_err])
        if start_err <= 5 and end_err <= 5:
            gold_matched += 1

    extracted = [i for i in extraction.items if i.status == ItemStatus.EXTRACTED]
    ratios = []
    body_len = 0
    covered = 0
    for item in extracted:
        if item.text and item.start is not None and item.end is not None:
            seg_len = item.end - item.start
            ratios.append(token_ratio(seg_len, len(item.text.strip())))
            covered += seg_len
            body_len = max(body_len, item.end)
    if not body_len:
        body_len = sum(len(i.text or "") for i in extracted) or 1

    toc_agreement = len(extracted) / max(len([i for i in extraction.items if i.start is not None]), 1)

    result = FilingEvalResult(
        accession=accession,
        ticker=filing.get("ticker"),
        cik=filing.get("cik"),
        split=filing.get("split", "train"),
        required_items_found=required_found,
        required_items_total=len(required),
        gold_boundary_errors=gold_errors,
        gold_items_matched=gold_matched,
        gold_items_total=len(gold_items),
        toc_header_agreement=min(1.0, toc_agreement),
        token_ratio_p50=statistics.median(ratios) if ratios else 0.0,
        char_coverage=covered / body_len if body_len else 0.0,
        tier0_extracted_count=len(extracted),
        incorporated_count=sum(
            1 for i in extraction.items if i.status == ItemStatus.INCORPORATED_BY_REFERENCE
        ),
        missing_count=sum(1 for i in extraction.items if i.status == ItemStatus.MISSING),
        low_confidence_count=sum(
            1 for i in extraction.items if i.status == ItemStatus.LOW_CONFIDENCE
        ),
        usd_per_filing=0.0,
        fallback_used=False,
    )
    result.failure_category = _classify_failure(
        required_found=result.required_items_found,
        required_total=result.required_items_total,
        gold_matched=result.gold_items_matched,
        gold_total=result.gold_items_total,
        low_confidence_count=result.low_confidence_count,
        gold_errors=gold_errors,
    )
    return result


def run_sec_eval(
    split: str = "train",
    *,
    manifest_path: Path | None = None,
    gold_dir: Path | None = None,
    use_arbiter: bool = False,
) -> list[FilingEvalResult]:
    manifest = load_manifest(manifest_path)
    required_items = manifest.get("required_items", ["1", "1A", "7", "8"])
    filings = [f for f in manifest["filings"] if f.get("split", "train") == split]
    return [
        evaluate_filing(f, gold_dir=gold_dir, use_arbiter=use_arbiter, required_items=required_items)
        for f in filings
    ]


def write_eval_csv(results: list[FilingEvalResult], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not results:
        output_path.write_text("task,status\nsec_10k,no_results\n", encoding="utf-8")
        return output_path

    rows = [r.to_csv_row() for r in results]
    fieldnames = list(rows[0].keys())
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def run_eval(split: str = "train", output_dir: str = "reports") -> str:
    """Run SEC manifest eval and write CSV. Returns output file path."""
    results = run_sec_eval(split=split, use_arbiter=False)
    out_dir = Path(output_dir)
    csv_path = out_dir / f"eval_{split}.csv"
    write_eval_csv(results, csv_path)
    latest = out_dir / "latest.csv"
    write_eval_csv(results, latest)
    return str(csv_path)
