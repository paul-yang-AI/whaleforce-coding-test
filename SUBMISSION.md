# Submission Checklist

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
- [x] `python scripts/run_heldout_snapshot.py` → `reports/heldout_snapshot.json`
- [x] `python scripts/demo_circuit_breaker.py` — budget demo
- [x] `.env` not tracked (`git ls-files .env` empty)

### Zeabur smoke (after push → auto redeploy)
- [ ] **Browser Agent**: preset "Navigate to Example.com" → Run → Refresh → `success` + **Result** block
- [ ] **Browser Agent**: preset "Hacker News" → verify multi-step + extracted title
- [ ] **SEC 10K**: MSFT from manifest → Extract → Item tree + 結構化文字閱讀視圖
- [ ] **SEC 10K**: Citi → Items 10–14 show `incorporated_by_reference`
- [ ] **SEC 10K**: JSON/Markdown 下載（metrics 下方，應即時無長等待）
- [ ] **Eval**: 即時紀錄 tab 可見 Agent + SEC runs；基準 tab 正常

### GitHub
- [x] Push latest commits: `git push origin master`
- [ ] **Settings → Change visibility → Public** (required by test brief)
- [x] Verify no secrets in history (`.env` never committed; history scan clean)

### Email to Whaleforce
Include:
1. Public Git URL
2. Frontend URL (Zeabur base — both tasks on same deployment)
3. Env notes: reviewers need their own `GEMINI_API_KEY` + `SEC_USER_AGENT`; `OPENROUTER_API_KEY` optional but improves agent search tasks
4. Pointer to `docs/analysis.md` and `prompts/ITERATION.md`

## Environment variables (Zeabur)

| Variable | Required | Example |
|----------|----------|---------|
| `GEMINI_API_KEY` | Yes | Google AI Studio |
| `SEC_USER_AGENT` | Yes | `WhaleforceCodingTest YourName you@email.com` |
| `OPENROUTER_API_KEY` | Recommended | Improves fallback when Gemini JSON parse fails |
| `RUN_BUDGET_USD` | No | `20` |
| `ENABLE_BLIND_CRITIC` | No | `false` (default); `true` for stricter agent terminal gate |
| `LLM_FALLBACK_ENABLED` | No | `true` (default) |

Port: **8501** (Networking must map to container 8501).

## Local verification

```powershell
.venv\Scripts\python.exe -m pytest -m unit
.venv\Scripts\python.exe -m pytest -m integration
.venv\Scripts\python.exe -m pytest -m eval
.venv\Scripts\python.exe scripts/run_eval.py --split train
.venv\Scripts\python.exe scripts/run_agent_eval.py
.venv\Scripts\python.exe scripts/run_heldout_snapshot.py
.venv\Scripts\python.exe scripts/demo_circuit_breaker.py
streamlit run streamlit_app.py
```

## Known eval numbers (honest, from CSV)

- **SEC train**: 3/3 filings `failure_category=ok`; Tier0 $0.00/filing
- **Agent train**: 5/5 success (100%); silent_failure=0; search validated on Wikipedia (DDG heldout)
- **Held-out BRK.B**: 4/4 required (local snapshot only)
