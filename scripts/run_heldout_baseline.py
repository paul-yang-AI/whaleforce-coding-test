"""Phase 0/3: run held-out SEC eval (Tier0 + optional LLM) and write baseline JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared_harness.env import load_env
from shared_harness.eval_runner import FilingEvalResult, run_sec_eval, write_eval_csv


def _result_row(r: FilingEvalResult, *, mode: str) -> dict:
    gold_p95 = max(r.gold_boundary_errors) if r.gold_boundary_errors else 0
    return {
        "mode": mode,
        "accession": r.accession,
        "ticker": r.ticker,
        "split": r.split,
        "required_items_found": r.required_items_found,
        "required_items_total": r.required_items_total,
        "tier0_extracted_count": r.tier0_extracted_count,
        "incorporated_count": r.incorporated_count,
        "missing_count": r.missing_count,
        "low_confidence_count": r.low_confidence_count,
        "toc_stub_count": r.toc_stub_count,
        "required_quality_failures": r.required_quality_failures,
        "required_prose_count": r.required_prose_count,
        "required_cross_ref_count": r.required_cross_ref_count,
        "expected_missing_ok_count": r.expected_missing_ok_count,
        "gold_items_matched": r.gold_items_matched,
        "gold_items_total": r.gold_items_total,
        "gold_boundary_p95": gold_p95,
        "token_ratio_p50": round(r.token_ratio_p50, 4),
        "char_coverage": round(r.char_coverage, 4),
        "failure_category": r.failure_category,
        "fallback_used": r.fallback_used,
    }


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Held-out SEC baseline (Tier0 + optional LLM)")
    parser.add_argument("--with-llm", action="store_true", help="Also run Tier1 LLM fallback path")
    parser.add_argument("--with-arbiter", action="store_true", help="Enable Tier2 arbiter")
    parser.add_argument("--output", default="reports")
    args = parser.parse_args()

    tier0 = run_sec_eval(split="heldout", use_arbiter=False, use_llm_fallback=False)
    rows = [_result_row(r, mode="tier0") for r in tier0]

    llm_rows: list[dict] = []
    if args.with_llm or args.with_arbiter:
        llm_results = run_sec_eval(
            split="heldout",
            use_arbiter=args.with_arbiter,
            use_llm_fallback=args.with_llm or args.with_arbiter,
        )
        llm_rows = [_result_row(r, mode="with_llm") for r in llm_results]

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = {
        "tier0": rows,
        "with_llm": llm_rows,
        "summary": {
            "tier0_filings": len(rows),
            "tier0_ok": sum(1 for r in rows if r["failure_category"] == "ok"),
            "tier0_required_pass": sum(
                1
                for r in rows
                if r["required_items_found"] == r["required_items_total"]
                and r["toc_stub_count"] == 0
            ),
            "with_llm_filings": len(llm_rows),
            "with_llm_ok": sum(1 for r in llm_rows if r["failure_category"] == "ok")
            if llm_rows
            else None,
        },
    }

    baseline_path = out_dir / "heldout_baseline.json"
    baseline_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(f"Wrote {baseline_path}")

    csv_path = out_dir / "eval_heldout.csv"
    write_eval_csv(tier0, csv_path)
    print(f"Wrote {csv_path}")

    snap_path = out_dir / "heldout_snapshot.json"
    snap_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {snap_path}")

    print(json.dumps(baseline["summary"], indent=2))


if __name__ == "__main__":
    main()
