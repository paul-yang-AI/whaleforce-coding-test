# Whaleforce AI Coding Test

Monorepo: Browser Agent (task1) + SEC 10-K extraction (task2) + shared harness.

**Start here**: [PLAN.md](PLAN.md)

## Harness-Aligned Design

> Design aligns with OpenAI's *Harness engineering* thesis: treat the model as an unstable reasoning engine and invest in verifiable harness layers (`shared_harness/`, L1 tests, Phase gates)—not in larger E2E prompts alone.

**Three Pillars:**

| Harness Principle | This Repo | Evidence |
|-------------------|-----------|----------|
| Context Scaffolding | `llm_router` cascade, `edgar_client` cache, `prompt_loader` | `test_pipeline_tier0_only` |
| Architectural Constraints | Pydantic schemas, `span integrity`, `llm_parse.py`, Blind Critic JSON-only | `test_span_integrity`, `test_llm_parse` |
| Entropy Management | `cost_tracker` circuit breaker, `eval_runner`, pytest L1/L2/L3 | `test_cost_tracker`, `reports/eval_train.csv` |

**Two-Layer Loop:**

| Loop | Object | Mapping |
|------|--------|---------|
| Dev Harness Loop | Human / Cursor / CI | Phase 0–3 gates, `pytest -m unit`, `ITERATION.md`, interleaved commits |
| Runtime Agent Loop | Task 1 user tasks | Plan→Act→Observe→Verify→Reflect; recovery strategy table; optional Blind Critic |

## Skill / SOP Layering

| Layer | Carrier | Who Decides | Example |
|-------|---------|-------------|---------|
| Deterministic SOP | Python + L1 pytest | Code (fixed) | `normalize.py`, `detect_incorporation()`, `recovery.py` strategy table |
| LLM SOP | `prompts/sops/*.md` via `prompt_loader` | `recovery.py` routes by `failure_type` | `sops/recovery.md`, `v1_boundary_arbiter.txt` |

No `skills/` folder. No agent self-select skill file.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then edit .env with your keys
pytest -m unit
python scripts/smoke_llm_models.py   # optional: verify LLM model IDs
streamlit run streamlit_app.py
```

Local secrets live in **`.env`** at repo root (gitignored). `shared_harness/env.py` loads it for Streamlit, pytest, and scripts. Existing shell env vars take precedence over `.env`.

## Deployment

Zeabur: single Docker service, Streamlit multi-page.

**Base URL**: https://whaleforce-coding-test.zeabur.app

| Page | Task | URL Path |
|------|------|----------|
| Home | Overview | `/` |
| **SEC 10K** | Task 2 — 10-K extraction | Sidebar → SEC 10K |
| **Browser Agent** | Task 1 — browser automation | Sidebar → Browser Agent |
| **Eval** | Dashboard (CSV + summary) | Sidebar → Eval |

**Git repo**: https://github.com/paul-yang-AI/whaleforce-coding-test (change to **Public** before emailing Whaleforce — see [SUBMISSION.md](SUBMISSION.md)).

Environment variables for demo:

| Variable | Required | Notes |
|----------|----------|-------|
| `GEMINI_API_KEY` | Yes | Tier1/Tier2 primary |
| `SEC_USER_AGENT` | Yes | `"CompanyName Contact email@domain.com"` |
| `RUN_BUDGET_USD` | No | Default `20` |
| `ENABLE_BLIND_CRITIC` | No | Default `false`; set `true` for terminal Tier1 gate (extra cost) |
| `OPENROUTER_API_KEY` | No | Optional code fallback only (not shown in UI) |
| `LLM_FALLBACK_ENABLED` | No | Default `true` in code; set `false` for Gemini-only |

## How AI Was Used

| Stage | Tool | Output |
|-------|------|--------|
| Architecture & PLAN | Cursor | PLAN.md, prompts/ |
| 10-K segment/metrics | Cursor TDD | `test_bs4_anchor.py`, `test_regex_boundary_fallback.py` |
| Agent recovery design | Cursor + PLAN | `recovery.py` route + `prompts/sops/recovery.md` |
| Eval design | Cursor | `manifest.json`, `tasks.yaml` |
| Debugging iteration | Cursor | `prompts/ITERATION.md` (v1→v2 with test evidence) |

See [prompts/ITERATION.md](prompts/ITERATION.md) for Failed Path → Resolution → Validation narratives.

## Output Steering & Contract-Driven Design

| Implementation | Design Term |
|----------------|-------------|
| Pydantic schemas (`sec_schema.py`, `common.py`) | Strong-typed output contracts |
| `llm_parse.py` | Cross-provider JSON normalization (strip `` ```json ``) |
| litellm + fallback + circuit breaker | Infrastructure behavior constraints |
| verify + metrics + span integrity | Post-validation (contract enforcement) |
| `compress_a11y` char budget (12000) | Input shaping — prevent recovery token explosion |
| WAL + `cancel_event` | Production resilience: DB concurrency + task lifecycle |
| Blind Critic (terminal gate) | External process verification |

**One-liner**: For iXBRL / dynamic DOM, use **Contract → Parse → Validate**, not prompt-and-pray.

## Model Cascade (litellm)

| Tier | Primary | Fallback | Use |
|------|---------|----------|-----|
| 1 | `gemini/gemini-3-flash-preview` | `openrouter/deepseek/deepseek-v4-pro` | plan, recovery, Blind Critic |
| 2 | `gemini/gemini-3.1-pro-preview` | `openrouter/qwen/qwen3.5-397b-a17b` | SEC boundary arbiter |

Fallback fires once per `(tier, call_site)` on 429/5xx/ValidationError. Skipped automatically if `OPENROUTER_API_KEY` is unset. `BudgetExceeded` → zero API.

## Task 1: Browser Agent

- **State machine**: Navigate → LLM Plan → Act → Observe → Verify (L0) → Reflect (only on failure)
- **Multi-step execution**: Step 0 navigates; steps 1+ are LLM-planned (click, type, scroll, press_key)
- **Result extraction**: When task completes, LLM extracts task-specific result from the page
- **Recovery**: classified by `FailureType` → strategy table (no blind retry)
- **Verify**: L0 heuristic per step + optional Blind Critic terminal gate (`ENABLE_BLIND_CRITIC=true`)
- **Cancel**: `cancel_event` checked at each step boundary; UI Stop button
- **Eval**: 8 tasks, 6 domains, 4 task_types (`tasks.yaml`); latest train CSV: **5/6 success, silent_failure=0**
- **L0 keyword verify**: Extracts domain names and quoted strings from task description; checks page content

### Supported Sites & Operations (from `reports/eval_train.csv`)

| Domain | Task Type | Status | Notes |
|--------|-----------|--------|-------|
| example.com | navigate | **Pass** | Title verification; 2 steps |
| news.ycombinator.com | extract | **Pass** | Top story title extracted |
| github.com | navigate | **Pass** | LLM-planned navigation to `/python/cpython` |
| httpbin.org | extract | **Flaky** | May hit `max_steps` when LLM budget exhausted mid-run |
| wikipedia.org | search | **Flaky** | Multi-step search; type auto-submits with Enter on search tasks |
| duckduckgo.com | search | **Flaky** | Same as Wikipedia — consent banner / dynamic DOM |
| sec.gov | navigate | Heldout | EDGAR search (not in train eval) |
| httpbin.org/forms | form | Heldout | POST form (not tuned) |

### Known Limitations & Failure Cases

**Deployment**
- **SQLite + WAL**: Zeabur container filesystem is ephemeral — agent run history and cost events reset on redeploy. Eval artifacts live in `reports/*.csv` (git-tracked) and SEC HTML cache on disk for the session.
- **Playwright memory**: Single concurrent agent run enforced in UI; multiple simultaneous runs may OOM on small containers (~1 GB).

**Browser Agent**
- **Login / CAPTCHA**: Agent reports `blocked` immediately; no bypass attempted
- **PDF / download URLs**: Detected and rejected before navigation (e.g. `arxiv.org/pdf/...`)
- **iFrame / Shadow DOM**: Not supported — a11y tree may miss embedded content
- **Multi-step search**: Wikipedia/DuckDuckGo may still hit `max_steps` on slow DOM or planner errors; search tasks auto-press Enter after type
- **Blind Critic off by default**: Zeabur uses L0 verify only; enable `ENABLE_BLIND_CRITIC=true` for stricter terminal gate (L2 tested)
- **Dynamic SPAs**: DOM may not stabilize within timeout; `extend_wait` recovery
- **Tab-close**: Use Stop button; tab close does not guarantee cancel

**SEC 10-K**
- **Confidence score**: Fixed 0.95 when contract checks pass — UI shows tier badge (regex/TOC/section_name) instead
- **Gold eval circularity**: Train gold boundaries regenerated from pipeline output (±5 char tolerance); held-out relies on contract metrics
- **Normalize flattens HTML**: Tables lose structure during extraction; readability improved via presentation-layer formatting
- **Incorporated by reference**: Content not inlined (anti-hallucination); DEF 14A auto-linked when CIK known
- **Naive LLM baseline**: Estimated from literature, not measured API calls

## Task 2: SEC 10-K

- **Pipeline**: Fetch → Normalize (iXBRL strip) → TOC/Regex segment → Validate (span integrity + metrics) → Arbiter (Tier2, disputed only) → Store
- **Item 1–16**: Every legal item has a status (`extracted | low_confidence | missing | incorporated_by_reference | not_applicable`)
- **Span integrity**: `body[start:end] == item.text` enforced before store; arbiter adjusts boundary only, never rewrites

### Good Examples (Tier0 high coverage)

| Ticker | Accession | Why it works well |
|--------|-----------|-------------------|
| **MSFT** | `0000950170-24-087843` | Full 6.8 MB iXBRL HTML, standard TOC, 22 items extracted at $0.00 |

### Difficult / Known-Issue Filings

| Ticker | Accession | Difficulty | Behavior |
|--------|-----------|-----------|----------|
| **INTC** | `0000050863-25-000009` | Heavy iXBRL, cross-reference index | 17 extracted, 5 incorporated (Items 10–14 via Proxy `(a)` footnote) |
| **C** (Citi) | `0000831001-25-000067` | Items 10–14 incorporated by reference | 12 extracted, 5 incorporated; section-name fallback for Business, Mine Safety |
| **BRK.B** | `0000950170-25-025210` | Heldout K-1 TOC variant | Local snapshot: 4/4 required, 21 extracted — see `reports/heldout_snapshot.json` |

### Generalization for Held-Out Filings

The segmenter uses a **three-layer fallback** designed for unseen filings:

1. **TOC anchor resolution** — follows `<a href="#...">` links in filing HTML
2. **Line-anchored regex** — `^\s*(?:ITEM|Item)\s+<id>` avoids inline false positives
3. **Section-name mapping** — 19 standard 10-K section titles (Business, Risk Factors, Properties, Legal Proceedings, Mine Safety, MD&A, etc.) for filings that omit "Item N" headers

Post-segmentation filters: `_is_page_reference_only` detects cross-reference index stubs; `_upgrade_short_segments` replaces them with section-name hits. Incorporation detection handles both explicit "incorporated by reference" language and `(a)`/`(b)` footnote markers.

**Anti-overfitting measures**: no ticker/accession branching in pipeline code; `char_coverage` measured against full normalized body (not max extracted offset); gold boundaries regenerated from pipeline output (acknowledged as circular — see `docs/analysis.md`).

### Not Yet Supported

- **PDF-primary filings**: Some older 10-K filings are PDF-only; this pipeline processes HTML only
- **Filing without TOC or Item headers**: Falls back to section-name regex, but may produce `missing` status
- **Non-English filings**: SEC foreign private issuers (20-F) not tested

## Tests

```bash
pytest -m unit                              # L1: deterministic, zero LLM
pytest -m integration                       # L2: mock integration
pytest -m eval                              # L3: SEC manifest + agent manifest
python scripts/run_eval.py --split train    # SEC → reports/eval_train.csv
python scripts/run_agent_eval.py            # SEC + agent live eval → CSV + summary
python scripts/run_heldout_snapshot.py      # BRK.B heldout (local only)
python scripts/demo_circuit_breaker.py      # BudgetExceeded demo
```

Held-out split: **not used for tuning** — results in `reports/heldout_snapshot.json` only.

## Eval Data

- **`task2_sec/eval/cache/`**: Real EDGAR HTML cached for offline CI (`edgar_client` rate-limit compliant). Use **Force refresh** in SEC UI for live filings.
- **`reports/eval_train.csv`**: Unified SEC + agent metrics (see Eval page).
- **`reports/eval_summary.json`**: Aggregate P50/P95/cost/success rate for `docs/analysis.md`.

## Design Trade-offs

| Ideal | This Project | Reason |
|-------|-------------|--------|
| Real-time SSE | DB + Refresh | Auditable, reproducible > animation |
| 12+ agent tasks | 8 deep tasks | Prove recovery, not success-rate padding |
| 16-item full gold | All status + 8-item gold | Realistic with no public ground truth |
| Two deployments | Single Docker, dual pages | One URL for both tasks |

## Future Work (Phase 4+)

1. **DSPy** — compile recovery/boundary prompts with eval metrics
2. **VLM / Set-of-Mark** — screenshot coordinate clicking for Canvas/React sites
3. **Multi-Agent Debate** — extractor vs. compliance auditor for boundary arbitration
4. **External Skill Trust** — allowlist + schema validation for third-party SOPs
5. **Entropy Gradient Routing** — route tasks to different LLM tiers based on confidence/uncertainty: high-confidence items stay on Tier0 (regex, $0); low-confidence items escalate to Tier1 (Flash) or Tier2 (Pro). This adaptive routing reduces cost while maintaining quality on difficult filings.

## License

MIT (adjust as needed)
