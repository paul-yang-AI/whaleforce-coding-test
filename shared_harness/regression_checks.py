"""Pure checks for private regression harness (no subprocess / network)."""

from __future__ import annotations

from typing import Any


def verify_sec_train_results(results: list[Any]) -> tuple[bool, str]:
    """Expect 3 train filings, all failure_category=ok, per-filing required counts."""
    if len(results) != 3:
        return False, f"expected 3 train filings, got {len(results)}"

    expected: dict[str, tuple[int, int]] = {
        "MSFT": (4, 4),
        "INTC": (3, 3),
        "C": (3, 3),
    }
    errors: list[str] = []
    for r in results:
        ticker = (r.ticker or "").upper()
        if r.failure_category != "ok":
            errors.append(f"{ticker}: failure_category={r.failure_category}")
            continue
        exp = expected.get(ticker)
        if not exp:
            errors.append(f"unexpected ticker {ticker}")
            continue
        found, total = r.required_items_found, r.required_items_total
        if (found, total) != exp:
            errors.append(f"{ticker}: required {found}/{total}, want {exp[0]}/{exp[1]}")
        if r.toc_stub_count > 0:
            errors.append(f"{ticker}: toc_stub_count={r.toc_stub_count}")

    if errors:
        return False, "; ".join(errors)
    return True, "3/3 ok (MSFT 4/4, INTC/Citi 3/3)"


def verify_agent_train_results(results: list[Any]) -> tuple[bool, str]:
    if len(results) != 5:
        return False, f"expected 5 train tasks, got {len(results)}"
    failures = [r for r in results if r.status != "success" or r.silent_failure]
    silent = sum(r.silent_failure for r in results)
    if failures:
        ids = [r.task_id for r in failures]
        return False, f"failed tasks: {ids}, silent_failure total={silent}"
    return True, "5/5 success, silent_failure=0"


def verify_sec_heldout_summary(summary: dict[str, Any]) -> tuple[bool, str]:
    ok = int(summary.get("tier0_ok", 0))
    total = int(summary.get("tier0_filings", 0))
    req = int(summary.get("tier0_required_pass", 0))
    if total < 8:
        return False, f"tier0_filings={total}, expected >= 8 cached"
    if ok < 6:
        return False, f"tier0_ok={ok}/{total}, expected >= 6/8"
    if req < 6:
        return False, f"tier0_required_pass={req}/{total}, expected >= 6/8"
    return True, f"{ok}/{total} ok, {req}/{total} strict required"


def verify_agent_heldout_summary(summary: dict[str, Any]) -> tuple[bool, str]:
    ok = int(summary.get("heldout_ok", 0))
    total = int(summary.get("heldout_tasks", 0))
    if total < 5:
        return False, f"heldout_tasks={total}, expected >= 5"
    if ok < 3:
        return False, f"heldout_ok={ok}/{total}, expected >= 3/5 (A+ baseline)"
    return True, f"{ok}/{total} failure_category=ok"
