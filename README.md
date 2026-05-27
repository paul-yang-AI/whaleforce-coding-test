# Whaleforce AI Coding Test

Monorepo: Browser Agent (task1) + SEC 10-K extraction (task2) + shared harness.

**Start here**: [PLAN.md](PLAN.md)

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

- Home
- **Browser_Agent** — task 1
- **SEC_10K** — task 2
- **Eval** — eval reports (optional)

## How AI Was Used

| Stage | Tool | Output |
|-------|------|--------|
| Architecture & PLAN | Cursor | PLAN.md, prompts/ |
| Implementation | Cursor TDD | tests + pipeline modules |
| Iteration | Cursor | prompts/ITERATION.md |

See [prompts/ITERATION.md](prompts/ITERATION.md) for v1→v2 prompt changes.

## Tests

```bash
pytest -m unit
pytest -m integration
pytest -m eval --split train   # via scripts/run_eval.py
```

Held-out split: local/demo only, not CI.

## License

MIT (adjust as needed)
