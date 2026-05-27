"""Optional LLM model ID smoke — requires API keys in .env or environment."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared_harness.env import load_env


def main() -> None:
    load_env()
    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
        print("SKIP: no GEMINI_API_KEY / GOOGLE_API_KEY (set in .env or environment)")
        sys.exit(0)

    from shared_harness import llm_config

    models = [
        ("Tier1 primary", llm_config.TIER1.primary),
        ("Tier2 primary", llm_config.TIER2.primary),
    ]
    if os.environ.get("OPENROUTER_API_KEY"):
        models.extend(
            [
                ("Tier1 fallback", llm_config.TIER1.fallback),
                ("Tier2 fallback", llm_config.TIER2.fallback),
            ]
        )
    else:
        print("Note: OPENROUTER_API_KEY not set — skipping fallback model smoke")

    try:
        import litellm
    except ImportError as exc:
        print(f"FAIL: litellm not installed: {exc}")
        sys.exit(1)

    failed = False
    for label, model in models:
        try:
            resp = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": 'Reply with JSON only: {"ok": true}'}],
                max_tokens=32,
            )
            content = (resp.choices[0].message.content or "")[:80]
            print(f"OK: {label} {model} -> {content}")
        except Exception as exc:
            failed = True
            print(f"FAIL: {label} {model} -> {exc}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
