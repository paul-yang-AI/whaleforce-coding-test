import pytest

from task2_sec.pipeline.segment import SpanIntegrityError, assert_span_integrity


@pytest.mark.unit
def test_span_integrity_passes() -> None:
    body = "Item 1. Business\nContent here."
    text = "Item 1. Business\nContent here."
    assert_span_integrity(body, 0, len(text), text)


@pytest.mark.unit
def test_span_integrity_fails_on_tampered_offset() -> None:
    body = "Item 1. Business\nContent here."
    with pytest.raises(SpanIntegrityError):
        assert_span_integrity(body, 0, 5, "WRONG")


@pytest.mark.unit
def test_span_integrity_raises_under_optimize_flag() -> None:
    """Explicit raise — not stripped by python -O (unlike assert)."""
    body = "hello world"
    with pytest.raises(SpanIntegrityError):
        assert_span_integrity(body, 0, 3, "bye")
