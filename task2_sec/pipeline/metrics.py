"""10-K extraction metrics — span integrity, token conservation, header retention."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RATIO_MIN = 0.85
HEADER_PREFIX_LEN = 200

HEADER_RE = re.compile(r"Item\s+[\dA-Z]+", re.IGNORECASE)

# Recognized section titles that serve as headers in filings without "Item N" format
_SECTION_TITLE_RE = re.compile(
    r"(?:Risk\s+Factors|Unresolved\s+Staff|Cybersecurity|Management.s\s+Discussion|"
    r"Quantitative\s+and\s+Qualitative|Financial\s+Statements|Controls\s+and\s+Procedures|"
    r"Directors[,\s]+Executive|Executive\s+Compensation|Security\s+Ownership|"
    r"Certain\s+Relationships|Principal\s+Account|Exhibits?\s+and\s+Financial|"
    r"Form\s+10-K\s+Summary|Changes\s+in\s+and\s+Disagreements|Properties|"
    r"Legal\s+Proceedings|Mine\s+Safety|Market\s+for\s+Registrant|Other\s+Information|"
    r"Market\s+Risk|Report\s+of\s+Independent|"
    r"Business)",
    re.IGNORECASE,
)


@dataclass
class MetricsResult:
    passed: bool
    confidence: float
    warnings: list[str] = field(default_factory=list)
    low_confidence: bool = False


def check_span_integrity(body: str, start: int, end: int, text: str) -> bool:
    return body[start:end] == text


def token_ratio(input_len: int, output_len: int) -> float:
    if input_len <= 0:
        return 0.0
    return output_len / input_len


def check_header_retention(text: str, item_id: str) -> bool:
    prefix = text[:HEADER_PREFIX_LEN]
    return bool(HEADER_RE.search(prefix) or _SECTION_TITLE_RE.search(prefix))


def evaluate_segment_metrics(
    body: str,
    start: int,
    end: int,
    item_id: str,
    *,
    ratio_min: float = RATIO_MIN,
) -> MetricsResult:
    warnings: list[str] = []
    text = body[start:end]
    if not check_span_integrity(body, start, end, text):
        warnings.append("span_integrity_fail")
        return MetricsResult(passed=False, confidence=0.0, warnings=warnings, low_confidence=True)

    if not check_header_retention(text, item_id):
        warnings.append("header_retention_fail")
        return MetricsResult(passed=False, confidence=0.3, warnings=warnings, low_confidence=True)

    seg_len = end - start
    ratio = token_ratio(seg_len, len(text.strip()))
    if ratio < ratio_min:
        warnings.append(f"token_ratio_low:{ratio:.2f}")
        return MetricsResult(passed=False, confidence=0.4, warnings=warnings, low_confidence=True)

    return MetricsResult(passed=True, confidence=0.95, warnings=warnings, low_confidence=False)


def evaluate_output_ratio(input_segment: str, output_text: str, *, ratio_min: float = RATIO_MIN) -> MetricsResult:
    """Post-arbiter check: output must not be a summary of input."""
    warnings: list[str] = []
    ratio = token_ratio(len(input_segment), len(output_text))
    if ratio < ratio_min:
        warnings.append(f"token_ratio_low:{ratio:.2f}")
        return MetricsResult(passed=False, confidence=0.4, warnings=warnings, low_confidence=True)
    return MetricsResult(passed=True, confidence=0.9, warnings=warnings, low_confidence=False)
