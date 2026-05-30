# Submission Checklist

## Reviewer Quick Start

1. **SEC 10K → 基準集（Train · 3）** — MSFT extract → Item tree + quality badges  
2. **SEC 10K → 泛化驗證（Held-out · 8）** — JPM (4/4 bank TOC pass) or AAPL 2010 (expected gap)  
3. **SEC 10K → 自訂報表** — paste any accession for unseen filing test  
4. **Eval → 基準評估 Train** — click「載入存檔結果」  
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
- [x] `python scripts/run_eval.py --split train`
- [x] `python scripts/run_agent_eval.py` → `reports/eval_train.csv` + `eval_summary.json`
- [x] `python scripts/run_heldout_baseline.py` → `reports/heldout_baseline.json`
- [x] `python scripts/run_heldout_snapshot.py` → `reports/heldout_snapshot.json`
- [x] `python scripts/demo_circuit_breaker.py` — budget demo
- [x] `.env` not tracked (`git ls-files .env` empty)

### Zeabur smoke (after push → auto redeploy)
- [ ] **Browser Agent**: preset "Navigate to Example.com" → Run → Refresh → `success` + **Result** block
- [ ] **Browser Agent**: preset "Hacker News" → verify multi-step + extracted title
- [ ] **SEC 10K → 基準集**: MSFT extract → **Required KPI 4/4** banner at top; INTC/Citi **3/3**
- [ ] **SEC 10K → 基準集**: Citi → Extract → 數秒內完成；**1A/7/8 + 9A/9B 長正文**；Item 10–14 incorporated；front 索引列 honest missing
- [ ] **Browser Agent → 泛化驗證**: held-out 4 任務 + 基線 badge（2/4 ok）
- [ ] **SEC 10K → 泛化驗證**: JPM → **4/4 required**；extract runs
- [ ] **SEC 10K**: JSON/Markdown 下載（metrics 下方，應即時無長等待）
- [ ] **Eval → 基準 Train**: 載入存檔結果正常
- [ ] **Eval → Held-out 基線**: SEC table 6/8 ok; **Agent** table 2/4 ok
- [ ] **Eval**: 即時紀錄 tab 可見 Agent + SEC runs

### GitHub
- [x] Push latest commits: `git push origin master`
- [ ] **Settings → Change visibility → Public** (required by test brief)
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
.venv\Scripts\python.exe scripts/run_eval.py --split train
.venv\Scripts\python.exe scripts/run_agent_eval.py
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
- **Agent held-out**: 2/4 ok — see `reports/agent_heldout_baseline.json`
