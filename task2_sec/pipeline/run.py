"""End-to-end 10-K extraction pipeline."""

from __future__ import annotations

from shared_harness.schemas.sec_schema import FilingExtraction
from task2_sec.pipeline.segment import Segmenter
from task2_sec.pipeline.validate import validate_segments


def extract_from_html(
    html: str,
    *,
    accession: str = "",
    cik: str | None = None,
    ticker: str | None = None,
    source_url: str | None = None,
    run_id: str | None = None,
    use_arbiter: bool = False,
    use_llm_fallback: bool = True,
) -> FilingExtraction:
    body, segments = Segmenter().segment(
        html, run_id=run_id, use_llm_fallback=use_llm_fallback
    )
    items = validate_segments(body, segments, run_id=run_id, use_arbiter=use_arbiter)
    return FilingExtraction(
        accession=accession,
        cik=cik,
        ticker=ticker,
        source_url=source_url,
        items=items,
    )
