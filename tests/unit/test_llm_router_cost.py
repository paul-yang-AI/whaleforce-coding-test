"""Tests for LLM cost estimation via litellm.completion_cost."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared_harness import llm_router


@pytest.mark.unit
def test_completion_usd_uses_litellm_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_router.litellm, "completion_cost", lambda **kw: 0.0042)
    response = MagicMock()
    usd = llm_router._completion_usd("gemini/gemini-3-flash-preview", response, 100, 50)
    assert usd == pytest.approx(0.0042)


@pytest.mark.unit
def test_completion_usd_falls_back_to_token_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**kw: object) -> float:
        raise RuntimeError("no pricing")

    monkeypatch.setattr(llm_router.litellm, "completion_cost", _boom)
    response = MagicMock()
    usd = llm_router._completion_usd("test/model", response, 1000, 500)
    assert usd == pytest.approx(0.0015)
