"""Pre-push end-to-end smoke test — verifies LLM, SEC pipeline, and agent basics."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared_harness.env import load_env


def check_llm() -> bool:
    """Verify Gemini API returns non-empty content."""
    import litellm
    from shared_harness import llm_config

    model = llm_config.TIER1.primary
    print(f"[LLM] Testing {model}...", end=" ")
    try:
        resp = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": 'Reply JSON: {"ok": true}'}],
            max_tokens=256,
        )
        content = resp.choices[0].message.content
        if not content or not content.strip():
            print(f"FAIL — empty content (thinking consumed all tokens)")
            return False
        print(f"OK — {content[:60]!r}")
        return True
    except Exception as exc:
        print(f"FAIL — {exc}")
        return False


def check_sec_pipeline() -> bool:
    """Run SEC extraction on a cached filing and verify items found."""
    print("[SEC] Testing pipeline on cached filing...", end=" ")
    try:
        from task2_sec.pipeline.fetch import fetch_filing_html
        from task2_sec.pipeline.run import extract_from_html

        import json
        manifest = json.loads(
            (_ROOT / "task2_sec" / "eval" / "manifest.json").read_text(encoding="utf-8")
        )
        filing = manifest["filings"][0]
        html, _cik = fetch_filing_html(filing["accession"])
        if len(html) < 1000:
            print(f"FAIL — cached HTML too small ({len(html)} chars)")
            return False

        result = extract_from_html(
            html,
            accession=filing["accession"],
            ticker=filing.get("ticker"),
            use_arbiter=False,
            use_llm_fallback=False,
        )
        extracted = sum(1 for i in result.items if i.status.value == "extracted")
        with_method = sum(1 for i in result.items if i.segment_method)
        if with_method < 5:
            print(f"FAIL — segment_method not populated ({with_method} items)")
            return False
        print(f"OK — {extracted} items extracted from {filing['ticker']}")
        return extracted >= 5
    except Exception as exc:
        print(f"FAIL — {exc}")
        return False


def check_agent_plan() -> bool:
    """Verify agent LLM planning returns a valid action (no browser needed)."""
    print("[Agent] Testing LLM planning...", end=" ")
    try:
        from shared_harness.llm_router import complete
        from shared_harness.schemas.common import AgentAction

        result = complete(
            tier=1,
            call_site="e2e_smoke_agent",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a browser automation planner. "
                        "Plan the next action as JSON: {done, action, selector, value, reasoning, result}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "TASK: Navigate to example.com\n"
                        "CURRENT URL: about:blank\n"
                        "PAGE CONTENT: empty\n"
                        "STEP: 0 of 10\n"
                        "Plan the next action."
                    ),
                },
            ],
            schema=AgentAction,
            task_type="agent",
            max_tokens=1024,
        )
        if hasattr(result, "action"):
            print(f"OK — action={result.action}, done={result.done}")
            return True
        print(f"FAIL — unexpected result type: {type(result)}")
        return False
    except Exception as exc:
        print(f"FAIL — {exc}")
        return False


def check_pdf_detection() -> bool:
    """Verify PDF/download URL detection without launching browser."""
    print("[Agent] Testing PDF URL detection...", end=" ")
    try:
        from task1_agent.agent.browser import PlaywrightExecutor

        ex = PlaywrightExecutor()
        if not ex._is_download_url("https://arxiv.org/pdf/2401.12345.pdf"):
            print("FAIL — PDF URL not detected")
            return False
        if ex._is_download_url("https://example.com"):
            print("FAIL — normal URL flagged as download")
            return False
        print("OK")
        return True
    except Exception as exc:
        print(f"FAIL — {exc}")
        return False


def check_agent_verify() -> bool:
    """Verify navigation vs terminal outcome logic without browser."""
    print("[Agent] Testing verify layer...", end=" ")
    try:
        from task1_agent.agent.verify import verify_navigation, verify_task_outcome

        nav = verify_navigation(
            url="https://en.wikipedia.org/wiki/Main_Page",
            page_text="Wikipedia Main Page " * 10,
            start_url="https://en.wikipedia.org",
        )
        if not nav.passed:
            print(f"FAIL — navigation: {nav.reason}")
            return False
        outcome = verify_task_outcome(
            task="Search for 'Alan Turing'",
            url="https://en.wikipedia.org/wiki/Alan_Turing",
            page_text="Alan Turing mathematician " * 5,
            start_url="https://en.wikipedia.org",
        )
        if not outcome.passed:
            print(f"FAIL — outcome: {outcome.reason}")
            return False
        print("OK")
        return True
    except Exception as exc:
        print(f"FAIL — {exc}")
        return False


def check_agent_task_mode() -> bool:
    """Verify extract vs act routing without browser."""
    print("[Agent] Testing task mode routing...", end=" ")
    try:
        from task1_agent.agent.extract import infer_task_mode

        assert infer_task_mode("Search DuckDuckGo for foo") == "act"
        assert infer_task_mode("Extract the title from the page") == "extract"
        print("OK")
        return True
    except Exception as exc:
        print(f"FAIL — {exc}")
        return False


def main() -> None:
    load_env()
    print("=" * 60)
    print("E2E Smoke Test — Pre-Push Verification")
    print("=" * 60)

    results = {
        "LLM": check_llm(),
        "SEC Pipeline": check_sec_pipeline(),
        "Agent Planning": check_agent_plan(),
        "PDF Detection": check_pdf_detection(),
        "Agent Verify": check_agent_verify(),
        "Agent Task Mode": check_agent_task_mode(),
    }

    print()
    print("=" * 60)
    all_ok = all(results.values())
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}]  {name}")

    print("=" * 60)
    if all_ok:
        print("All checks passed — safe to push.")
    else:
        print("Some checks FAILED — fix before pushing!")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
