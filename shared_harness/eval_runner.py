"""SEC manifest + agent task eval — score pipelines, export CSV."""

from __future__ import annotations

import csv
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from shared_harness.cost_tracker import get_run_cost, get_run_llm_call_count
from shared_harness.schemas.sec_schema import ItemStatus
from task2_sec.pipeline.content_quality import assess_required_item
from task2_sec.pipeline.fetch import fetch_filing_html
from task2_sec.pipeline.metrics import token_ratio
from task2_sec.pipeline.run import extract_from_html

_EVAL_ROOT = Path(__file__).resolve().parent.parent / "task2_sec" / "eval"
DEFAULT_MANIFEST = _EVAL_ROOT / "manifest.json"
DEFAULT_GOLD_DIR = _EVAL_ROOT / "gold"
DEFAULT_CACHE_DIR = _EVAL_ROOT / "cache"
DEFAULT_TASKS = Path(__file__).resolve().parent.parent / "task1_agent" / "eval" / "tasks.yaml"

EVAL_CSV_FIELDS = [
    "task",
    "record_id",
    "domain",
    "task_type",
    "split",
    "status",
    "steps",
    "elapsed_s",
    "recovery_count",
    "llm_calls",
    "silent_failure",
    "required_items_found",
    "required_items_total",
    "gold_items_matched",
    "gold_items_total",
    "gold_boundary_p95",
    "toc_header_agreement",
    "token_ratio_p50",
    "char_coverage",
    "tier0_extracted_count",
    "incorporated_count",
    "missing_count",
    "low_confidence_count",
    "toc_stub_count",
    "required_quality_failures",
    "required_prose_count",
    "required_cross_ref_count",
    "expected_missing_ok_count",
    "usd_per_run",
    "fallback_used",
    "failure_category",
    "extracted_result",
]


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
    toc_stub_count: int = 0
    required_quality_failures: int = 0
    required_prose_count: int = 0
    required_cross_ref_count: int = 0
    expected_missing_ok_count: int = 0
    usd_per_filing: float = 0.0
    fallback_used: bool = False
    failure_category: str = "ok"

    def to_csv_row(self) -> dict[str, Any]:
        gold_p95 = max(self.gold_boundary_errors) if self.gold_boundary_errors else 0
        return {
            "task": "sec_10k",
            "record_id": self.accession,
            "domain": self.ticker or "",
            "task_type": "extract",
            "split": self.split,
            "status": "ok" if self.failure_category == "ok" else "failed",
            "steps": "",
            "elapsed_s": "",
            "recovery_count": 0,
            "llm_calls": 0,
            "silent_failure": 0,
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
            "toc_stub_count": self.toc_stub_count,
            "required_quality_failures": self.required_quality_failures,
            "required_prose_count": self.required_prose_count,
            "required_cross_ref_count": self.required_cross_ref_count,
            "expected_missing_ok_count": self.expected_missing_ok_count,
            "usd_per_run": round(self.usd_per_filing, 6),
            "fallback_used": self.fallback_used,
            "failure_category": self.failure_category,
            "extracted_result": "",
        }


@dataclass
class AgentEvalResult:
    task_id: str
    domain: str
    task_type: str
    split: str
    status: str
    steps: int
    elapsed_s: float
    recovery_count: int = 0
    llm_calls: int = 0
    usd_per_task: float = 0.0
    silent_failure: int = 0
    failure_category: str = "ok"
    extracted_result: str = ""
    error: str | None = None

    def to_csv_row(self) -> dict[str, Any]:
        return {
            "task": "agent",
            "record_id": self.task_id,
            "domain": self.domain,
            "task_type": self.task_type,
            "split": self.split,
            "status": self.status,
            "steps": self.steps,
            "elapsed_s": round(self.elapsed_s, 2),
            "recovery_count": self.recovery_count,
            "llm_calls": self.llm_calls,
            "silent_failure": self.silent_failure,
            "required_items_found": "",
            "required_items_total": "",
            "gold_items_matched": "",
            "gold_items_total": "",
            "gold_boundary_p95": "",
            "toc_header_agreement": "",
            "token_ratio_p50": "",
            "char_coverage": "",
            "tier0_extracted_count": "",
            "incorporated_count": "",
            "missing_count": "",
            "low_confidence_count": "",
            "toc_stub_count": "",
            "required_quality_failures": "",
            "required_prose_count": "",
            "required_cross_ref_count": "",
            "expected_missing_ok_count": "",
            "usd_per_run": round(self.usd_per_task, 6),
            "fallback_used": "",
            "failure_category": self.failure_category,
            "extracted_result": (self.extracted_result or "")[:500],
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


def _required_item_satisfied(item) -> bool:
    """Strict required-item check: extracted TOC stubs do not count as found."""
    quality = assess_required_item(item.item_id, item.text, item.status.value)
    return quality in {"ok", "incorporated", "low_confidence", "cross_ref"}


def _classify_failure(
    *,
    required_found: int,
    required_total: int,
    gold_matched: int,
    gold_total: int,
    low_confidence_count: int,
    gold_errors: list[int],
    toc_stub_count: int = 0,
) -> str:
    if toc_stub_count > 0:
        return "toc_stub_required_item"
    if required_found < required_total:
        return "missing_item_header"
    if gold_total and gold_matched < gold_total:
        if any(e > 50 for e in gold_errors):
            return "arbiter_boundary_error"
        return "span_integrity_fail"
    if low_confidence_count > 0:
        return "low_confidence"
    return "ok"


def _filing_cache_exists(accession: str, cache_dir: Path | None = None) -> bool:
    cache_path = (cache_dir or DEFAULT_CACHE_DIR) / f"{accession}.html"
    return cache_path.exists()


def evaluate_filing(
    filing: dict[str, Any],
    *,
    gold_dir: Path | None = None,
    use_arbiter: bool = False,
    use_llm_fallback: bool = False,
    run_id: str | None = None,
    required_items: list[str] | None = None,
) -> FilingEvalResult:
    accession = filing["accession"]
    html, _resolved_cik, _source_url = fetch_filing_html(accession)
    extraction = extract_from_html(
        html,
        accession=accession,
        cik=filing.get("cik"),
        ticker=filing.get("ticker"),
        run_id=run_id,
        use_arbiter=use_arbiter,
        use_llm_fallback=use_llm_fallback,
    )

    required = filing.get("required_items") or required_items or ["1", "1A", "7", "8"]
    expected_missing = filing.get("expected_missing") or []
    by_id = {item.item_id: item for item in extraction.items}
    required_found = sum(
        1 for item_id in required if item_id in by_id and _required_item_satisfied(by_id[item_id])
    )
    toc_stub_count = 0
    required_quality_failures = 0
    required_prose_count = 0
    required_cross_ref_count = 0
    for item_id in required:
        item = by_id.get(item_id)
        if item is None:
            continue
        quality = assess_required_item(item_id, item.text, item.status.value)
        if quality == "ok":
            required_prose_count += 1
        elif quality == "cross_ref":
            required_cross_ref_count += 1
        if quality == "toc_stub":
            toc_stub_count += 1
        if quality in {"toc_stub", "missing"}:
            required_quality_failures += 1

    expected_missing_ok_count = sum(
        1
        for item_id in expected_missing
        if item_id in by_id and by_id[item_id].status == ItemStatus.MISSING
    )

    gold = _load_gold(accession, gold_dir)
    gold_items = (gold or {}).get("items", {})
    gold_errors: list[int] = []
    gold_matched = 0
    gold_boundary_total = 0
    for item_id, expected in gold_items.items():
        if "start" not in expected or "end" not in expected:
            continue
        gold_boundary_total += 1
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

    from task2_sec.pipeline.normalize import normalize as _normalize_html
    full_body = _normalize_html(html)
    full_body_len = len(full_body) or 1

    extracted = [i for i in extraction.items if i.status == ItemStatus.EXTRACTED]
    ratios = []
    covered = 0
    for item in extracted:
        if item.text and item.start is not None and item.end is not None:
            seg_len = item.end - item.start
            ratios.append(token_ratio(seg_len, len(item.text.strip())))
            covered += seg_len
    body_len = full_body_len

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
        gold_items_total=gold_boundary_total,
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
        toc_stub_count=toc_stub_count,
        required_quality_failures=required_quality_failures,
        required_prose_count=required_prose_count,
        required_cross_ref_count=required_cross_ref_count,
        expected_missing_ok_count=expected_missing_ok_count,
        usd_per_filing=0.0,
        fallback_used=use_llm_fallback or use_arbiter,
    )
    result.failure_category = _classify_failure(
        required_found=result.required_items_found,
        required_total=result.required_items_total,
        gold_matched=result.gold_items_matched,
        gold_total=result.gold_items_total,
        low_confidence_count=result.low_confidence_count,
        gold_errors=gold_errors,
        toc_stub_count=toc_stub_count,
    )
    return result


def run_sec_eval(
    split: str = "train",
    *,
    manifest_path: Path | None = None,
    gold_dir: Path | None = None,
    cache_dir: Path | None = None,
    use_arbiter: bool = False,
    use_llm_fallback: bool = False,
) -> list[FilingEvalResult]:
    manifest = load_manifest(manifest_path)
    required_items = manifest.get("required_items", ["1", "1A", "7", "8"])
    filings = [f for f in manifest["filings"] if f.get("split", "train") == split]
    results: list[FilingEvalResult] = []
    for filing in filings:
        if filing.get("cache_optional") and not _filing_cache_exists(
            filing["accession"], cache_dir
        ):
            continue
        results.append(
            evaluate_filing(
                filing,
                gold_dir=gold_dir,
                use_arbiter=use_arbiter,
                use_llm_fallback=use_llm_fallback,
                required_items=required_items,
            )
        )
    return results


def write_eval_csv(results: list[FilingEvalResult | AgentEvalResult], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not results:
        output_path.write_text(
            ",".join(EVAL_CSV_FIELDS) + "\n",
            encoding="utf-8",
        )
        return output_path

    rows = [r.to_csv_row() for r in results]
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVAL_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def load_tasks(path: Path | None = None) -> dict[str, Any]:
    tasks_path = path or DEFAULT_TASKS
    return yaml.safe_load(tasks_path.read_text(encoding="utf-8"))


def _classify_agent_failure(status: str, error: str | None) -> str:
    if status == "success":
        return "ok"
    if status == "blocked":
        return "captcha_or_login"
    if status == "cancelled":
        return "cancelled"
    err = (error or "").lower()
    if "budget" in err:
        return "budget_exceeded"
    if "blind critic" in err:
        return "verify_critic_reject"
    if "recovery exhausted" in err:
        return "recovery_exhausted"
    if "max steps" in err:
        return "max_steps"
    if "outcome verification" in err or "not found in page" in err or "task terms not" in err:
        return "outcome_verify_fail"
    if "planner unavailable" in err or "err_name_not_resolved" in err or "timeout" in err:
        return "infrastructure"
    return "reasoning_failure"


def _count_recovery_steps(run_id: str) -> int:
    from shared_harness.job_store import get_connection

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM run_steps WHERE run_id = ? AND action LIKE 'recovery:%'",
            (run_id,),
        ).fetchone()
        return int(row["cnt"])
    finally:
        conn.close()


def evaluate_agent_task(
    task: dict[str, Any],
    *,
    executor: Any,
) -> AgentEvalResult:
    from shared_harness import job_store
    from task1_agent.agent.loop import run as agent_run

    task_id = task["id"]
    run_id = job_store.create_run("agent", label=task.get("description", task_id)[:120])
    t0 = time.perf_counter()
    result = agent_run(
        task_description=task["description"],
        start_url=task.get("start_url", "https://example.com"),
        run_id=run_id,
        execute_action=executor,
    )
    elapsed = time.perf_counter() - t0

    recovery_count = _count_recovery_steps(run_id)
    llm_calls = get_run_llm_call_count(run_id)
    usd = get_run_cost(run_id)

    silent = 0
    if result.status == "success":
        task_type = task.get("task_type", "")
        if task_type in ("extract", "search", "form"):
            if not (result.extracted_result or "").strip():
                silent = 1
        elif task_type == "navigate":
            expected_domain = task.get("domain", "")
            final_url = result.final_url or (result.steps[-1].url if result.steps else "")
            if expected_domain and expected_domain not in final_url:
                silent = 1

    failure_category = _classify_agent_failure(result.status, result.error)
    if silent:
        failure_category = "silent_failure"

    return AgentEvalResult(
        task_id=task_id,
        domain=task.get("domain", ""),
        task_type=task.get("task_type", ""),
        split=task.get("split", "train"),
        status=result.status,
        steps=len(result.steps),
        elapsed_s=elapsed,
        recovery_count=recovery_count,
        llm_calls=llm_calls,
        usd_per_task=usd,
        silent_failure=silent,
        failure_category=failure_category,
        extracted_result=result.extracted_result,
        error=result.error,
    )


def run_agent_eval(
    split: str = "train",
    *,
    tasks_path: Path | None = None,
    executor: Any | None = None,
) -> list[AgentEvalResult]:
    manifest = load_tasks(tasks_path)
    tasks = [t for t in manifest["tasks"] if t.get("split", "train") == split]

    if executor is not None:
        return [evaluate_agent_task(t, executor=executor) for t in tasks]

    from task1_agent.agent.browser import PlaywrightExecutor

    executor = PlaywrightExecutor(headless=True, timeout_ms=20000)
    executor.start()
    try:
        return [evaluate_agent_task(t, executor=executor) for t in tasks]
    finally:
        executor.close()


def run_eval(
    split: str = "train",
    output_dir: str = "reports",
    *,
    include_agent: bool = False,
    use_arbiter: bool = False,
    use_llm_fallback: bool = False,
) -> str:
    """Run eval harness and write CSV. Returns output file path."""
    results: list[FilingEvalResult | AgentEvalResult] = list(
        run_sec_eval(
            split=split,
            use_arbiter=use_arbiter,
            use_llm_fallback=use_llm_fallback,
        )
    )
    if include_agent and split == "train":
        results.extend(run_agent_eval(split="train"))

    out_dir = Path(output_dir)
    csv_path = out_dir / f"eval_{split}.csv"
    write_eval_csv(results, csv_path)
    latest = out_dir / "latest.csv"
    write_eval_csv(results, latest)
    return str(csv_path)


def summarize_eval(results: list[FilingEvalResult | AgentEvalResult]) -> dict[str, Any]:
    sec = [r for r in results if isinstance(r, FilingEvalResult)]
    agent = [r for r in results if isinstance(r, AgentEvalResult)]

    summary: dict[str, Any] = {}
    if sec:
        summary["sec_filings"] = len(sec)
        summary["sec_ok"] = sum(1 for r in sec if r.failure_category == "ok")
        summary["sec_tier0_pct"] = 100.0
        summary["sec_usd_p50"] = statistics.median([r.usd_per_filing for r in sec])
    if agent:
        successes = sum(1 for r in agent if r.status == "success")
        summary["agent_tasks"] = len(agent)
        summary["agent_success_rate"] = successes / len(agent) if agent else 0.0
        summary["agent_silent_failures"] = sum(r.silent_failure for r in agent)
        summary["agent_recovery_total"] = sum(r.recovery_count for r in agent)
        summary["agent_llm_calls_total"] = sum(r.llm_calls for r in agent)
        latencies = [r.elapsed_s for r in agent]
        summary["agent_latency_p50"] = statistics.median(latencies) if latencies else 0.0
        summary["agent_latency_p95"] = (
            sorted(latencies)[int(len(latencies) * 0.95) - 1] if len(latencies) >= 2 else (latencies[0] if latencies else 0.0)
        )
        costs = [r.usd_per_task for r in agent]
        summary["agent_usd_p50"] = statistics.median(costs) if costs else 0.0
    return summary
