"""LLM segment classify path (ENABLE_SEC_LLM_CLASSIFY)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from shared_harness.schemas.common import SegmentClassDecision
from task2_sec.pipeline.segment_classify import SegmentClass, classify_segment_text_with_llm


@pytest.mark.unit
def test_classify_with_llm_uses_schema_param(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SEC_LLM_CLASSIFY", "true")
    unknown = "Short ambiguous excerpt " * 5

    with patch("shared_harness.llm_router.complete") as mock_complete:
        mock_complete.return_value = SegmentClassDecision(klass="real_content")
        result = classify_segment_text_with_llm(unknown, "7", run_id="run-test")

    assert result == SegmentClass.REAL_CONTENT
    mock_complete.assert_called_once()
    _, kwargs = mock_complete.call_args
    assert kwargs.get("schema") is SegmentClassDecision
    assert "response_model" not in kwargs
