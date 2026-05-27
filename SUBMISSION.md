# Submission Checklist

## 1. Private push (now)

1. On GitHub: **New repository** → name `whaleforce-coding-test` → **Private** → do **not** add README/license (repo already has commits).
2. From repo root:

```powershell
.\scripts\push_private.ps1 -GitHubUser YOUR_GITHUB_USERNAME
```

Or manually:

```powershell
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/whaleforce-coding-test.git
git push -u origin master
```

3. Confirm `.env` is **not** in the repo: `git ls-files .env` should print nothing.

## 2. Zeabur deploy

1. [Zeabur](https://zeabur.com/) → New Project → Import GitHub repo (Private OK).
2. Build: Dockerfile (auto-detected). Port: **8501**.
3. Set environment variables (Zeabur dashboard):

| Variable | Required | Example |
|----------|----------|---------|
| `GEMINI_API_KEY` | Yes | from Google AI Studio |
| `SEC_USER_AGENT` | Yes | `WhaleforceCodingTest YourName you@email.com` |
| `OPENROUTER_API_KEY` | No | fallback only |
| `RUN_BUDGET_USD` | No | `20` |

4. After deploy, copy the public URL (e.g. `https://xxx.zeabur.app`).
5. Update `README.md` → **Deployment** → `Base URL: ...` (or note in submission email).

## 3. Smoke test on Zeabur

- **Browser Agent**: task `Navigate to example.com and verify the title` → Refresh → status `success`.
- **SEC 10K**: select MSFT from manifest → Extract → items with status badges.
- **Eval**: page shows `eval_train.csv`.

## 4. Before emailing Whaleforce

- [ ] GitHub repo → Settings → **Change visibility to Public**
- [ ] Email includes: **public Git URL**, **frontend URL** (same Zeabur base for both tasks), env notes if needed
- [ ] Do not commit `.env` or API keys

## Local verification (optional)

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/run_eval.py --split train
.venv\Scripts\python.exe scripts/run_agent_eval.py
streamlit run streamlit_app.py
```
