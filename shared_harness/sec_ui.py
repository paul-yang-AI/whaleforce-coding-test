"""Pure helpers for SEC 10-K Streamlit page (unit-testable without Streamlit)."""


def sec_result_matches_context(
    *,
    source: str,
    accession: str,
    result_source: str | None,
    result_accession: str | None,
) -> bool:
    """True when cached extraction belongs to the active tab + accession selection."""
    accession = (accession or "").strip()
    if not accession or not result_accession or not result_source:
        return False
    return result_source == source and result_accession.strip() == accession
