"""Load repo-root `.env` into os.environ (does not override existing vars)."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOADED = False


def load_env() -> None:
    global _LOADED
    if _LOADED:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _LOADED = True
        return
    load_dotenv(_REPO_ROOT / ".env", override=False)
    _LOADED = True


def repo_root() -> Path:
    return _REPO_ROOT
