"""Eval runner stub — full implementation on Day 4."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared_harness.env import load_env


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="train")
    parser.add_argument("--output", default="reports")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "eval_stub.csv"
    csv_path.write_text("phase,status\n0,scaffold\n", encoding="utf-8")
    print(f"Wrote {csv_path} (split={args.split})")


if __name__ == "__main__":
    main()
