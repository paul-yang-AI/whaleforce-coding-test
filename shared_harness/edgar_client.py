"""SEC EDGAR client — single entry point for all SEC HTTP requests."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / "task2_sec" / "eval" / "cache"
_MIN_INTERVAL_SEC = 0.11
_lock = threading.Lock()
_last_request_at = 0.0
_user_agent_validated = False


class EdgarClientError(Exception):
    """Base EDGAR client error."""


class EdgarConfigurationError(EdgarClientError):
    """Missing or invalid SEC configuration."""


class EdgarRateLimitedError(EdgarClientError):
    """SEC returned 403/429."""


def _validate_user_agent() -> str:
    global _user_agent_validated
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise EdgarConfigurationError(
            "SEC_USER_AGENT is required (format: 'CompanyName ContactName email@domain.com')"
        )
    if not re.search(r"\S+\s+\S+\s+\S+@\S+\.\S+", ua):
        raise EdgarConfigurationError(
            f"SEC_USER_AGENT format invalid: {ua!r}. Expected 'Company Contact email@domain.com'"
        )
    _user_agent_validated = True
    return ua


def get_user_agent() -> str:
    if not _user_agent_validated:
        return _validate_user_agent()
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise EdgarConfigurationError("SEC_USER_AGENT is required")
    return ua


def cache_path(accession: str) -> Path:
    safe = accession.replace("/", "-")
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{safe}.html"


def _throttle() -> None:
    global _last_request_at
    with _lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < _MIN_INTERVAL_SEC:
            time.sleep(_MIN_INTERVAL_SEC - elapsed)
        _last_request_at = time.monotonic()


def _http_get(url: str) -> httpx.Response:
    """Single throttled HTTP GET with SEC User-Agent."""
    ua = get_user_agent()
    _throttle()
    headers = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
    if response.status_code in (403, 429):
        raise EdgarRateLimitedError(f"SEC rate limited: HTTP {response.status_code}")
    response.raise_for_status()
    return response


def resolve_filing_url(accession: str, cik: str | None = None) -> str:
    """Resolve the primary 10-K HTML document URL from EDGAR filing index.

    Parses the EDGAR filing index and identifies the main filing document
    by filtering out navigation links, exhibits, and iXBRL viewer wrappers.
    """
    accession_nodash = accession.replace("-", "")
    if cik:
        cik_clean = cik.lstrip("0") or "0"
    else:
        cik_clean = accession.split("-")[0].lstrip("0") or "0"

    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_clean}"
        f"/{accession_nodash}/{accession}-index.htm"
    )
    logger.info("Resolving filing URL from index: %s", index_url)

    response = _http_get(index_url)
    html = response.text

    base_path = f"/Archives/edgar/data/{cik_clean}/{accession_nodash}/"

    htm_links = re.findall(
        r'href="([^"]+\.htm[l]?)"',
        html,
        re.IGNORECASE,
    )
    if not htm_links:
        raise EdgarClientError(
            f"No .htm documents found in filing index: {index_url}"
        )

    filing_docs: list[str] = []
    for link in htm_links:
        # Handle /ix?doc= iXBRL viewer links — extract the actual document path
        ix_match = re.search(r"/ix\?doc=(.+)$", link)
        if ix_match:
            doc_path = ix_match.group(1)
            filing_docs.append(f"https://www.sec.gov{doc_path}")
            continue

        # Skip site navigation and non-filing links
        if link in ("/index.htm", "/index.html"):
            continue
        if "/searchedgar/" in link or "/edgar/searchedgar" in link:
            continue
        if "-index" in link:
            continue
        if "R1.htm" in link or "R2.htm" in link:
            continue
        # Skip exhibits
        if "-exh" in link.lower() or "exhibit" in link.lower():
            continue

        # Build full URL
        if link.startswith("/Archives/"):
            full = f"https://www.sec.gov{link}"
        elif link.startswith("/"):
            continue  # Other absolute paths are site links, not filing docs
        elif link.startswith("http"):
            full = link
        else:
            full = f"https://www.sec.gov{base_path}{link}"

        filing_docs.append(full)

    if not filing_docs:
        raise EdgarClientError(
            f"Could not identify filing document in index: {index_url}"
        )

    # Prefer the main 10-K document: typically named {ticker}-{date}.htm
    # and is the first document (not _d2, _d3 which are supplementary)
    primary = filing_docs[0]
    for doc in filing_docs:
        if "_d2" not in doc and "_d3" not in doc:
            primary = doc
            break

    logger.info("Resolved filing URL: %s", primary)
    return primary


def fetch_filing_html(
    accession: str,
    url: str | None = None,
    *,
    cik: str | None = None,
    force_refresh: bool = False,
) -> str:
    """Fetch filing HTML from EDGAR.

    Args:
        accession: SEC accession number (e.g. '0000789019-24-000045')
        url: Direct URL to 10-K HTML. If None, auto-resolved from EDGAR index.
        cik: CIK number (helps resolve URL). Extracted from accession if not given.
        force_refresh: If True, bypass cache and fetch live from EDGAR.

    Returns:
        HTML content of the filing.
    """
    path = cache_path(accession)

    if not force_refresh and path.exists():
        return path.read_text(encoding="utf-8", errors="replace")

    if not url:
        url = resolve_filing_url(accession, cik=cik)

    try:
        response = _http_get(url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            logger.warning("URL returned 404, resolving from EDGAR index: %s", url)
            url = resolve_filing_url(accession, cik=cik)
            response = _http_get(url)
        else:
            raise

    html = response.text
    path.write_text(html, encoding="utf-8")
    return html


def reset_throttle_for_tests() -> None:
    global _last_request_at, _user_agent_validated
    with _lock:
        _last_request_at = 0.0
    _user_agent_validated = False
