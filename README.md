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

**Base URL** (fill after deploy): `https://<your-app>.zeabur.app`

| Page | Task | URL Path |
|------|------|----------|
| Home | Overview | `/` |
| **SEC 10K** | Task 2 — 10-K extraction | Sidebar → SEC 10K |
| **Browser Agent** | Task 1 — browser automation | Sidebar → Browser Agent |
| **Eval** | Dashboard (CSV) | Sidebar → Eval |

**Private Git → Public before submit**: push to a private GitHub repo during development; change repo visibility to **Public** when emailing Whaleforce. See [SUBMISSION.md](SUBMISSION.md).

Environment variables required for demo:
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) — Gemini primary
- `OPENROUTER_API_KEY` — fallback (optional; primary-only still works)
- `SEC_USER_AGENT` — `"CompanyName Contact email@domain.com"`
- `RUN_BUDGET_USD` — default `20`

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

Fallback fires once per `(tier, call_site)` on 429/5xx/ValidationError. `BudgetExceeded` → zero API.

## Task 1: Browser Agent

- **State machine**: Plan → Act → Observe → Verify (L0) → Reflect (only on failure)
- **Recovery**: classified by `FailureType` → strategy table (no blind retry)
- **Verify**: L0 heuristic per step + optional Blind Critic terminal gate (`ENABLE_BLIND_CRITIC=true`)
- **Cancel**: `cancel_event` checked at each step boundary; UI Stop button
- **Eval**: 8 tasks, 6 domains, 4 task_types (`tasks.yaml`); `silent_failure == 0`

### Supported Sites & Operations

| Domain | Task Type | Status | Notes |
|--------|-----------|--------|-------|
| example.com | navigate | **Pass** | Title verification, baseline smoke |
| httpbin.org | extract | **Pass** | JSON response extraction (headers, forms) |
| news.ycombinator.com | extract | **Pass** | Top story title extraction |
| duckduckgo.com | search | **Pass** | Search results page verification |
| wikipedia.org | search | **Known issue** | Requires multi-step: type in search box + submit |
| github.com | navigate | **Known issue** | Requires multi-step: navigate from root to nested repo path |
| sec.gov | navigate | Heldout | EDGAR filing search (not tuned) |
| httpbin.org/forms | form | Heldout | POST form submission (not tuned) |

### Known Limitations & Failure Cases

- **Login / CAPTCHA**: Agent reports `blocked` immediately; no bypass attempted
- **Multi-step form interaction**: Current executor handles navigate+observe; tasks requiring type→submit need LLM-planned action sequences (Phase 5)
- **Dynamic SPAs (React/Vue)**: DOM may not stabilize within timeout; mitigation: `extend_wait` recovery strategy
- **Tab-close**: Streamlit cannot detect browser tab close; use Stop button for guaranteed cancel
- **Example failure**: `wikipedia_search` — navigates to `en.wikipedia.org` but verify rejects because "Alan Turing" keyword not found (search form not submitted)

## Task 2: SEC 10-K

- **Pipeline**: Fetch → Normalize (iXBRL strip) → TOC/Regex segment → Validate (span integrity + metrics) → Arbiter (Tier2, disputed only) → Store
- **Item 1–16**: Every legal item has a status (`extracted | low_confidence | missing | incorporated_by_reference | not_applicable`)
- **Span integrity**: `body[start:end] == item.text` enforced before store; arbiter adjusts boundary only, never rewrites

### Good Examples (Tier0 high coverage)

| Ticker | Accession | Why it works well |
|--------|-----------|-------------------|
| **MSFT** | `0000789019-24-000045` | Clean HTML, standard TOC, 8 items extracted at $0.00 |

### Difficult / Known-Issue Filings

| Ticker | Accession | Difficulty | Behavior |
|--------|-----------|-----------|----------|
| **INTC** | `0000050863-25-000009` | Heavy iXBRL tags, dense tables, headers split across `<b>`/`<span>` | Normalize strips tags → regex fallback succeeds; 6 items extracted |
| **C** (Citi) | `0000831001-25-000067` | Items 10–14 are "incorporated by reference to Proxy Statement" | Correctly flagged `incorporated_by_reference` with `text=None`; no hallucinated content |
| **BRK.B** | `0000950170-25-025210` | K-1 page numbering in TOC, unusual structure | Heldout — not tuned against |

### Not Yet Supported

- **PDF-primary filings**: Some older 10-K filings are PDF-only; this pipeline processes HTML only
- **Filing without TOC or Item headers**: Falls back to regex, but may produce `missing` status
- **Non-English filings**: SEC foreign private issuers (20-F) not tested

## Tests

```bash
pytest -m unit                              # L1: deterministic, zero LLM
pytest -m integration                       # L2: mock integration
pytest -m eval                              # L3: manifest eval (uses cache fixtures)
python scripts/run_eval.py --split train    # export reports/eval_train.csv
```

Held-out split (`--split heldout`): local/demo only, not used for tuning.

## Eval Fixtures

The HTML files under `task2_sec/eval/cache/` are **synthetic 10-K fixtures** crafted to
exercise the pipeline's TOC, regex fallback, iXBRL normalization, and incorporation-by-reference
detection. They are intentionally committed for reproducible offline CI. For real-filing
validation, supply a valid `SEC_USER_AGENT` and run with a live EDGAR URL (cache-miss path).

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

## License

MIT (adjust as needed)
