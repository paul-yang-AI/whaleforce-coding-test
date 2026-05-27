"""SEC 10-K extraction UI — Part → Item tree from cached filings."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from shared_harness.schemas.sec_schema import ItemStatus, STANDARD_ITEMS
from task2_sec.pipeline.fetch import fetch_filing_html
from task2_sec.pipeline.run import extract_from_html

_MANIFEST = Path(__file__).resolve().parent.parent / "task2_sec" / "eval" / "manifest.json"
_PART_ORDER = ["I", "II", "III", "IV"]


def _load_manifest() -> list[dict]:
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return [f for f in data["filings"] if f.get("split", "train") == "train"]


def _status_badge(status: ItemStatus) -> str:
    mapping = {
        ItemStatus.EXTRACTED: "✅ extracted",
        ItemStatus.LOW_CONFIDENCE: "⚠️ low confidence",
        ItemStatus.MISSING: "❌ missing",
        ItemStatus.INCORPORATED_BY_REFERENCE: "📎 incorporated by reference",
        ItemStatus.NOT_APPLICABLE: "➖ not applicable",
    }
    return mapping.get(status, status.value)


def _render_item(item) -> None:
    badge = _status_badge(item.status)
    header = f"Item {item.item_id} — {badge} (confidence {item.confidence:.2f})"
    if item.status == ItemStatus.EXTRACTED and item.text:
        with st.expander(header, expanded=item.item_id in {"1", "7", "8"}):
            st.text(item.text[:8000] + ("…" if len(item.text) > 8000 else ""))
            if item.warnings:
                st.caption("Warnings: " + ", ".join(item.warnings))
    elif item.status == ItemStatus.INCORPORATED_BY_REFERENCE:
        st.warning(header)
        for w in item.warnings:
            st.caption(w)
    elif item.status == ItemStatus.LOW_CONFIDENCE:
        st.warning(header)
        if item.text:
            st.text(item.text[:4000])
    elif item.status == ItemStatus.MISSING:
        st.error(header)
    else:
        st.info(header)


st.title("SEC 10-K Extraction")
st.caption("Hybrid Tier0 pipeline — BS4/regex segmentation with span integrity checks.")

filings = _load_manifest()
labels = [f"{f['ticker']} — {f['accession']} ({f.get('label', '')})" for f in filings]
choice = st.selectbox("Select filing (train manifest)", labels, index=0)
selected = filings[labels.index(choice)]

run = st.button("Extract", type="primary")

if run:
    accession = selected["accession"]
    with st.spinner(f"Extracting {accession}…"):
        try:
            html = fetch_filing_html(accession)
            result = extract_from_html(
                html,
                accession=accession,
                cik=selected.get("cik"),
                ticker=selected.get("ticker"),
                use_arbiter=False,
            )
            st.session_state["sec_result"] = result
        except Exception as exc:
            st.error(f"Extraction failed: {exc}")

result = st.session_state.get("sec_result")
if result:
    extracted = sum(1 for i in result.items if i.status == ItemStatus.EXTRACTED)
    incorporated = sum(1 for i in result.items if i.status == ItemStatus.INCORPORATED_BY_REFERENCE)
    missing = sum(1 for i in result.items if i.status == ItemStatus.MISSING)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Extracted", extracted)
    c2.metric("Incorporated by ref", incorporated)
    c3.metric("Missing", missing)
    c4.metric("Total items", len(STANDARD_ITEMS))

    by_part: dict[str, list] = {p: [] for p in _PART_ORDER}
    by_part["Other"] = []
    for item in result.items:
        part = item.part or "Other"
        by_part.setdefault(part, []).append(item)

    for part in _PART_ORDER + (["Other"] if by_part.get("Other") else []):
        items = by_part.get(part) or []
        if not items:
            continue
        st.subheader(f"Part {part}")
        for item in items:
            _render_item(item)

    st.download_button(
        "Download JSON",
        data=result.model_dump_json(indent=2),
        file_name=f"{result.accession or 'filing'}.json",
        mime="application/json",
    )
