# Architecture & Invariants

> **Role of this file**: frozen **architecture constraints** and initial phase summary — not a living task list.
> **Full iteration log** (Failed Path → Resolution → Validation): [`prompts/ITERATION.md`](prompts/ITERATION.md).
> **Submission audit trail** (per test brief): Git history + `prompts/` + README + [`docs/analysis.md`](docs/analysis.md).

## Goal

Monorepo with **task1_agent/** (browser agent), **task2_sec/** (10-K pipeline), **shared_harness/** (LLM router, cost, EDGAR, job store).

## Architecture (do not drift without updating tests + ITERATION)

- **Frontend**: Streamlit multi-page, single Dockerfile (Playwright base image)
- **LLM**: litellm only; Tier0 = rules/BS4 (zero token); Tier1/2 via `llm_router`
- **SEC**: all HTTP via `edgar_client.py`; cache at `task2_sec/eval/cache/`
- **Agent**: sync Playwright in background thread; SQLite job store (no SSE)
- **Validation**: span integrity `body[start:end]==text`; classified recovery via `STRATEGY_TABLE` (no blind retry)
- **Eval discipline**: train split for KPI; held-out for generalization — do not tune on held-out

## MVI Stop-Loss

If behind schedule: keep SEC train CSV + L1 tests + 2 agent smoke; cut Blind Critic / extra L2 / non-essential UI.

## Env

```
SEC_USER_AGENT="Company Name email@domain.com"
GEMINI_API_KEY=...
OPENROUTER_API_KEY=...
RUN_BUDGET_USD=20
```

## Shipped tracks (completed)

- **Phase 0–3**: scaffold → SEC pipeline + UI → agent loop + recovery → docs, Zeabur, L3 eval (see `git log`)
- **P0**: eval honesty — `content_quality.py`, strict required-item check, `toc_stub_required_item`
- **P1–P2**: Tier0 robustness; surgical LLM — `segment_classify.py`, arbiter, `--tier0-only` / `--with-llm`
- **Eval expansion**: 11-filing manifest; `heldout_baseline.json` (5/8 ok); honest JPM / AAPL / KSCP gaps
- **Prompts audit**: `prompts/README.md`, ITERATION entries, arbiter SOP sync
- **UI presentation**: SEC Train / Held-out / Custom tabs; Eval held-out baseline tab
- **Harness hardening (Phase 1)**: per-task Playwright context reset; `llm_budget_guard`; `litellm.completion_cost`; `SQLITE_JOURNAL_MODE`

Details and test evidence for each: [`prompts/ITERATION.md`](prompts/ITERATION.md).

## Historical — Phase gates (Phase 0–3, all done)

| Phase | Deliver | Gate |
|-------|---------|------|
| **0** | Scaffold + harness stubs + Docker smoke | `pytest -m unit`; Playwright smoke |
| **1** | SEC fetch→segment→validate→UI | L1 SEC; `test_sec_manifest` |
| **2** | Agent loop + recovery + UI | `test_recovery_routing`; smoke tasks |
| **3** | README, ITERATION, analysis, deploy | L3 train CSV |

Original day-by-day schedule (Day 1–7) retired; timeline preserved in commit history.
