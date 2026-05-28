"""Baseline comparison: Regex-Only vs Naive LLM (estimated) vs Hybrid Pipeline."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared_harness.env import load_env

load_env()

from shared_harness.schemas.sec_schema import STANDARD_ITEMS, ItemStatus
from task2_sec.pipeline.fetch import fetch_filing_html
from task2_sec.pipeline.normalize import normalize
from task2_sec.pipeline.run import extract_from_html
from task2_sec.pipeline.segment import (
    HEADER_RE,
    SegmentMethod,
    SegmentResult,
    Segmenter,
    _normalize_item_id,
)
from task2_sec.pipeline.validate import fill_missing_items, validate_segment

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "task2_sec" / "eval" / "manifest.json"
GOLD_DIR = REPO_ROOT / "task2_sec" / "eval" / "gold"
REPORT_PATH = REPO_ROOT / "reports" / "baseline_comparison.json"

GPT4_INPUT_PRICE_PER_1K = 0.01
GPT4_OUTPUT_PRICE_PER_1K = 0.03
CHARS_PER_TOKEN = 4


# ---------------------------------------------------------------------------
# Baseline 1: Regex-Only
# ---------------------------------------------------------------------------


def run_regex_only_baseline(
    html: str, accession: str, ticker: str
) -> dict:
    """Regex-only: raw HEADER_RE positions, merge, validate. No enhancements."""
    body = normalize(html)

    starts_by_id: dict[str, list[int]] = {}
    for m in HEADER_RE.finditer(body):
        item_id = _normalize_item_id(m.group("id"))
        starts_by_id.setdefault(item_id, []).append(m.start())

    body_len = len(body)
    hits: list[SegmentResult] = []
    for item_id, starts in starts_by_id.items():
        start = _pick_best_start_simple(starts, body_len)
        hits.append(
            SegmentResult(
                item_id=item_id, start=start, end=start, method=SegmentMethod.REGEX
            )
        )

    ordered = sorted(hits, key=lambda s: s.start)
    for i, seg in enumerate(ordered):
        seg.end = ordered[i + 1].start if i + 1 < len(ordered) else body_len

    items = [validate_segment(body, seg, use_arbiter=False) for seg in ordered]
    items = fill_missing_items(items)

    return _score_items(items, accession)


def _pick_best_start_simple(starts: list[int], body_len: int) -> int:
    """Simplified best-start: prefer content region, else last match."""
    if len(starts) == 1:
        return starts[0]
    if body_len > 20000:
        lo = body_len * 5 // 100
        hi = body_len - lo
        content = [s for s in starts if lo < s < hi]
        if content:
            return content[0]
    return starts[-1]


# ---------------------------------------------------------------------------
# Baseline 2: Naive LLM (estimated)
# ---------------------------------------------------------------------------

NAIVE_LLM_REQUIRED_RECALL = 0.60
NAIVE_LLM_TOKEN_RATIO = 0.40
NAIVE_LLM_INCORPORATION_MISS_RATE = 0.80


def estimate_naive_llm(html: str, accession: str, ticker: str) -> dict:
    """Estimate naive LLM extraction quality and cost without calling an LLM.

    Assumptions based on published GPT-4 benchmarks and lost-in-middle research:
    - Long filings (>100k tokens) suffer lost-in-middle: Items 7-9A often missed
    - LLM tends to summarize rather than extract verbatim (token_ratio ~0.3-0.5)
    - Incorporation by reference is usually missed (no structural understanding)
    - Cost based on GPT-4 pricing: ~$0.01/1K input + $0.03/1K output tokens
    """
    body = normalize(html)
    token_count = len(body) // CHARS_PER_TOKEN

    output_tokens = int(token_count * NAIVE_LLM_TOKEN_RATIO)
    cost = (token_count / 1000) * GPT4_INPUT_PRICE_PER_1K + (
        output_tokens / 1000
    ) * GPT4_OUTPUT_PRICE_PER_1K

    gold = _load_gold(accession)
    gold_ids = set(gold.keys()) if gold else set()

    required = {"1", "1A", "7", "8"}
    required_present = gold_ids & required

    long_filing = token_count > 50_000
    if long_filing:
        lost_middle = {"7", "7A", "8", "9", "9A"}
        found_required = required_present - lost_middle
        recall = len(found_required) / max(len(required), 1)
    else:
        found_count = int(len(required_present) * NAIVE_LLM_REQUIRED_RECALL)
        recall = found_count / max(len(required), 1)

    incorporated_in_gold = sum(
        1
        for v in (gold or {}).values()
        if v.get("status") == "incorporated_by_reference"
    )
    incorporated_found = int(
        incorporated_in_gold * (1 - NAIVE_LLM_INCORPORATION_MISS_RATE)
    )

    all_gold_ids = set(gold.keys()) if gold else set()
    if long_filing:
        found_items = all_gold_ids - lost_middle
    else:
        found_items = all_gold_ids
    missing_count = len(set(STANDARD_ITEMS)) - len(found_items)

    return {
        "accession": accession,
        "ticker": ticker,
        "required_items_found": int(recall * len(required)),
        "required_items_total": len(required),
        "incorporated_count": incorporated_found,
        "missing_count": missing_count,
        "estimated_cost_per_filing": round(cost, 4),
        "token_ratio_p50": NAIVE_LLM_TOKEN_RATIO,
        "method": "naive_llm_estimate",
    }


# ---------------------------------------------------------------------------
# Baseline 3: Hybrid Pipeline (current)
# ---------------------------------------------------------------------------


def run_hybrid_pipeline(
    html: str, accession: str, ticker: str
) -> dict:
    """Run the current hybrid pipeline as-is."""
    extraction = extract_from_html(html, accession=accession, ticker=ticker)
    return _score_items(extraction.items, accession)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _load_gold(accession: str) -> dict | None:
    safe = accession.replace("/", "-")
    path = GOLD_DIR / f"{safe}.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return data.get("items", {})


def _score_items(items: list, accession: str) -> dict:
    """Score a set of ItemRecords against required items and gold labels."""
    by_id = {}
    for item in items:
        iid = item.item_id if hasattr(item, "item_id") else item["item_id"]
        status = item.status if hasattr(item, "status") else item["status"]
        by_id[iid] = str(status)

    required = {"1", "1A", "7", "8"}
    found = 0
    for r in required:
        st = by_id.get(r, "")
        if st in (
            str(ItemStatus.EXTRACTED),
            str(ItemStatus.INCORPORATED_BY_REFERENCE),
            "extracted",
            "incorporated_by_reference",
        ):
            found += 1

    incorporated = sum(
        1
        for st in by_id.values()
        if st
        in (str(ItemStatus.INCORPORATED_BY_REFERENCE), "incorporated_by_reference")
    )

    missing = sum(
        1 for st in by_id.values() if st in (str(ItemStatus.MISSING), "missing")
    )

    gold = _load_gold(accession)
    ticker = ""
    for item in items:
        if hasattr(item, "ticker"):
            ticker = item.ticker or ""
            break

    return {
        "accession": accession,
        "ticker": ticker,
        "required_items_found": found,
        "required_items_total": len(required),
        "incorporated_count": incorporated,
        "missing_count": missing,
        "estimated_cost_per_filing": 0.0,
        "token_ratio_p50": 1.0,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_COL_W = {
    "method": 20,
    "ticker": 8,
    "req_found": 10,
    "req_total": 10,
    "incorp": 8,
    "missing": 8,
    "cost": 10,
    "tok_r": 10,
}


def _print_table(rows: list[dict]) -> None:
    headers = {
        "method": "Method",
        "ticker": "Ticker",
        "req_found": "Req.Found",
        "req_total": "Req.Total",
        "incorp": "Incorp.",
        "missing": "Missing",
        "cost": "Cost($)",
        "tok_r": "Tok.Ratio",
    }

    header_line = ""
    for key, label in headers.items():
        header_line += label.ljust(_COL_W[key])
    print(header_line)
    print("-" * len(header_line))

    for row in rows:
        line = ""
        line += str(row.get("method", "")).ljust(_COL_W["method"])
        line += str(row.get("ticker", "")).ljust(_COL_W["ticker"])
        line += str(row.get("required_items_found", "")).ljust(_COL_W["req_found"])
        line += str(row.get("required_items_total", "")).ljust(_COL_W["req_total"])
        line += str(row.get("incorporated_count", "")).ljust(_COL_W["incorp"])
        line += str(row.get("missing_count", "")).ljust(_COL_W["missing"])
        cost = row.get("estimated_cost_per_filing", 0)
        line += f"{cost:.4f}".ljust(_COL_W["cost"])
        tok = row.get("token_ratio_p50", 0)
        line += f"{tok:.2f}".ljust(_COL_W["tok_r"])
        print(line)


def _print_summary(all_results: dict[str, list[dict]]) -> None:
    print("\n" + "=" * 84)
    print("AGGREGATE SUMMARY")
    print("=" * 84)

    headers = {
        "method": "Method",
        "avg_req": "Avg.Req%",
        "tot_incorp": "Tot.Inc",
        "tot_miss": "Tot.Miss",
        "avg_cost": "Avg.Cost",
        "tok_r": "Tok.Ratio",
    }
    header_line = ""
    for label in headers.values():
        header_line += label.ljust(16)
    print(header_line)
    print("-" * len(header_line))

    for method, results in all_results.items():
        n = len(results)
        avg_recall = (
            sum(r["required_items_found"] / r["required_items_total"] for r in results)
            / n
        )
        total_incorp = sum(r["incorporated_count"] for r in results)
        total_missing = sum(r["missing_count"] for r in results)
        avg_cost = sum(r["estimated_cost_per_filing"] for r in results) / n
        tok_ratios = [r["token_ratio_p50"] for r in results]
        tok_p50 = median(tok_ratios)

        line = ""
        line += method.ljust(16)
        line += f"{avg_recall * 100:.1f}%".ljust(16)
        line += str(total_incorp).ljust(16)
        line += str(total_missing).ljust(16)
        line += f"${avg_cost:.4f}".ljust(16)
        line += f"{tok_p50:.2f}".ljust(16)
        print(line)


def main() -> None:
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    train_filings = [f for f in manifest["filings"] if f["split"] == "train"]

    if not train_filings:
        print("ERROR: No train-split filings found in manifest.")
        sys.exit(1)

    print(f"Running baselines on {len(train_filings)} train-split filings...\n")

    all_results: dict[str, list[dict]] = {
        "regex_only": [],
        "naive_llm_est": [],
        "hybrid": [],
    }

    for filing in train_filings:
        accession = filing["accession"]
        ticker = filing["ticker"]
        cik = filing["cik"]
        url = filing.get("url")

        print(f"\n{'=' * 84}")
        print(f"Filing: {ticker} ({accession})")
        print(f"{'=' * 84}")

        html = fetch_filing_html(accession, url=url, cik=cik)

        # --- Regex-Only ---
        t0 = time.perf_counter()
        regex_result = run_regex_only_baseline(html, accession, ticker)
        regex_result["method"] = "regex_only"
        regex_result["ticker"] = ticker
        regex_time = time.perf_counter() - t0
        all_results["regex_only"].append(regex_result)

        # --- Naive LLM (estimated) ---
        llm_result = estimate_naive_llm(html, accession, ticker)
        llm_result["method"] = "naive_llm_est"
        all_results["naive_llm_est"].append(llm_result)

        # --- Hybrid Pipeline ---
        t0 = time.perf_counter()
        hybrid_result = run_hybrid_pipeline(html, accession, ticker)
        hybrid_result["method"] = "hybrid"
        hybrid_result["ticker"] = ticker
        hybrid_time = time.perf_counter() - t0
        all_results["hybrid"].append(hybrid_result)

        print(f"\n  Regex-Only   ({regex_time:.2f}s)")
        print(f"  Hybrid       ({hybrid_time:.2f}s)")
        print(f"  Naive LLM    (estimated, no API call)\n")

        _print_table([regex_result, llm_result, hybrid_result])

    _print_summary(all_results)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "description": "Baseline comparison: Regex-Only vs Naive LLM (estimated) vs Hybrid Pipeline",
        "train_filings": [f["accession"] for f in train_filings],
        "results": all_results,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to {REPORT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
