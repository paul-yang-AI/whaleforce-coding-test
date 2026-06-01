# Submission Checklist

## Reviewer Quick Start

1. **SEC 10K → 基準集（Train · 3）** — MSFT extract → Item tree + quality badges  
2. **SEC 10K → 泛化驗證（Held-out · 8）** — JPM (4/4 bank TOC pass) or AAPL 2010 (expected gap)  
3. **SEC 10K → 自訂報表** — paste any accession for unseen filing test  
4. **Eval → 基準評估 Train** — click「載入存檔結果」（`eval_train.csv` 應含 3 SEC + 5 agent 列）  
5. **Eval → Held-out 基線** — read `heldout_baseline.json` table (6/8 ok)

> Manifest has **11 filings** (3 train + 8 held-out). Train-only dropdown is intentional eval discipline.

## URLs (for Whaleforce email)

| Item | URL |
|------|-----|
| **Git repo** | https://github.com/paul-yang-AI/whaleforce-coding-test |
| **Frontend (both tasks)** | https://whaleforce-coding-test.zeabur.app |
| SEC 10-K page | Same base → sidebar **SEC 10K** |
| Browser Agent page | Same base → sidebar **Browser Agent** |
| Eval dashboard | Same base → sidebar **Eval** |

## Pre-submit checklist

### Code & tests
- [x] `pytest -m unit` — L1 all green
- [x] `pytest -m integration` — L2 all green
- [x] `pytest -m eval` — L3 SEC + agent manifest
- [x] `python scripts/run_eval.py --split train --tier0-only` — SEC train only (do **not** overwrite `eval_train.csv` after agent eval)
- [x] `python scripts/run_agent_eval.py` — **last** step for train CSV: SEC + Agent → `reports/eval_train.csv` + `eval_summary.json` (8 rows)
- [x] `python scripts/run_heldout_baseline.py` → `reports/heldout_baseline.json`
- [x] `python scripts/run_heldout_baseline.py --with-llm` → `with_llm` in baseline (6/8 ok; AAPL 2010 still 2/4 required on current snapshot)
- [x] `python scripts/run_agent_heldout_baseline.py` → `reports/agent_heldout_baseline.json`
- [x] `python scripts/run_heldout_snapshot.py` → `reports/heldout_snapshot.json`
- [x] `python scripts/demo_circuit_breaker.py` — budget demo
- [x] `.env` not tracked (`git ls-files .env` empty)

### Automated pre-check (local, 2026-06-01)

- [x] `python scripts/e2e_smoke.py` — 6/6 PASS
- [x] `python scripts/run_private_regression.py --skip-pytest --skip-smoke` — SEC 3/3, held-out 6/8, agent 3/5
- [x] `reports/eval_train.csv` — 8 rows (3 SEC + 5 agent); `heldout_baseline.json` with `with_llm`
- [x] Zeabur health `/_stcore/health` → HTTP 200

手動瀏覽器步驟見 [docs/ZEABUR_SMOKE.md](docs/ZEABUR_SMOKE.md).

### Zeabur smoke (after push → auto redeploy)
- [ ] **Browser Agent**: preset "Navigate to Example.com" → Run → Refresh → `success` + **Result** block
- [ ] **Browser Agent**: preset "Hacker News" → verify multi-step + extracted title
- [ ] **SEC 10K → 基準集**: MSFT extract → **Required KPI 4/4** banner at top; INTC/Citi **3/3**
- [ ] **SEC 10K → 基準集**: Citi → Extract → 數秒內完成；**1A/7/8 + 9A/9B 長正文**；Item 10–14 incorporated；front 索引列 honest missing
- [ ] **Browser Agent → 泛化驗證**: held-out 5 任務 + 基線 badge（3/5 ok：forms + python_docs + quotes）
- [ ] **SEC 10K → 泛化驗證**: JPM → **4/4 required**；extract runs
- [ ] **SEC 10K**: JSON/Markdown 下載（metrics 下方，應即時無長等待）
- [ ] **Eval → 基準 Train**: 載入存檔結果正常
- [ ] **Eval → Held-out 基線**: SEC table 6/8 ok; **Agent** table 3/5 ok
- [ ] **Eval**: 即時紀錄 tab 可見 Agent + SEC runs

### GitHub
- [x] Push latest commits: `git push origin master`
- [x] **Settings → Change visibility → Public** (required by test brief)
- [x] Verify no secrets in history (`.env` never committed; history scan clean)

### Email to Whaleforce
Include:
1. Public Git URL
2. Frontend URL (Zeabur base — both tasks on same deployment)
3. Env notes: reviewers need their own `GEMINI_API_KEY` + `SEC_USER_AGENT`; `OPENROUTER_API_KEY` optional but improves agent search tasks
4. Pointer to `docs/analysis.md`, `prompts/ITERATION.md`, `prompts/README.md`, and **Reviewer Quick Start** (top of this file)

## Environment variables (Zeabur)

| Variable | Required | Example |
|----------|----------|---------|
| `GEMINI_API_KEY` | Yes | Google AI Studio |
| `SEC_USER_AGENT` | Yes | `WhaleforceCodingTest YourName you@email.com` |
| `OPENROUTER_API_KEY` | Recommended | Improves fallback when Gemini JSON parse fails |
| `RUN_BUDGET_USD` | No | `20` |
| `ENABLE_BLIND_CRITIC` | No | `false` (default); `true` for stricter agent terminal gate |
| `LLM_FALLBACK_ENABLED` | No | `true` (default) |
| `SQLITE_JOURNAL_MODE` | No | `WAL` (default); use `TRUNCATE` on NFS / multi-instance if needed |

Port: **8501** (Networking must map to container 8501).

## Local verification

```powershell
.venv\Scripts\python.exe -m pytest -m unit
.venv\Scripts\python.exe -m pytest -m integration
.venv\Scripts\python.exe -m pytest -m eval
.venv\Scripts\python.exe scripts/run_eval.py --split train --tier0-only
.venv\Scripts\python.exe scripts/run_agent_eval.py
.venv\Scripts\python.exe scripts/run_heldout_baseline.py --with-llm
.venv\Scripts\python.exe scripts/run_heldout_baseline.py
.venv\Scripts\python.exe scripts/run_agent_heldout_baseline.py
.venv\Scripts\python.exe scripts/cache_heldout_filings.py
.venv\Scripts\python.exe scripts/run_heldout_snapshot.py
.venv\Scripts\python.exe scripts/demo_circuit_breaker.py
streamlit run streamlit_app.py
```

## Known eval numbers (honest, from CSV / baseline)

- **SEC train**: 3/3 filings `failure_category=ok` (MSFT 4/4, INTC/Citi 3/3 required); Tier0 $0.00/filing
- **SEC held-out (Tier0, 8 cached)**: 6/8 ok; 6/8 strict required pass — see `reports/heldout_baseline.json`
- **Agent train**: 5/5 success; silent_failure=0
- **Agent held-out**: **3/5** ok（forms + python_docs + quotes）；SEC/DDG max_steps — **no silent failure**
- **SEC held-out + LLM** (`with_llm` in baseline): 6/8 ok; AAPL 2010 **2/4** required (unchanged vs Tier0 on current snapshot)
