"""SEC 10-K 結構化抽取 — 信心條、狀態卡片、分部瀏覽。"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import streamlit as st

from shared_harness import job_store
from shared_harness.sec_ui import sec_result_matches_context
from shared_harness.edgar_client import (
    build_sec_viewer_url,
    find_proxy_filing,
    format_filing_search_label,
    search_filings,
    search_quality_hint,
)
from shared_harness.schemas.sec_schema import FilingExtraction, ItemStatus, STANDARD_ITEMS
from task2_sec.pipeline.fetch import fetch_filing_html
from task2_sec.pipeline.run import extract_from_html
from task2_sec.pipeline.segment import is_page_reference_text

_MANIFEST = Path(__file__).resolve().parent.parent / "task2_sec" / "eval" / "manifest.json"
_PART_ORDER = ["I", "II", "III", "IV"]

_ITEM_NAMES = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "[Reserved]",
    "7": "Management's Discussion and Analysis (MD&A)",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}


def _load_manifest() -> list[dict]:
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return [f for f in data["filings"] if f.get("split", "train") == "train"]


def _status_color(status: ItemStatus) -> str:
    return {
        ItemStatus.EXTRACTED: "#10b981",
        ItemStatus.LOW_CONFIDENCE: "#f59e0b",
        ItemStatus.MISSING: "#ef4444",
        ItemStatus.INCORPORATED_BY_REFERENCE: "#6366f1",
        ItemStatus.NOT_APPLICABLE: "#9ca3af",
    }.get(status, "#6b7280")


def _status_icon(status: ItemStatus) -> str:
    return {
        ItemStatus.EXTRACTED: "✅",
        ItemStatus.LOW_CONFIDENCE: "⚠️",
        ItemStatus.MISSING: "❌",
        ItemStatus.INCORPORATED_BY_REFERENCE: "📎",
        ItemStatus.NOT_APPLICABLE: "➖",
    }.get(status, "❓")


_METHOD_LABELS: dict[str, tuple[str, str]] = {
    "toc": ("TOC 錨點", "#059669"),
    "regex": ("正則匹配", "#2563eb"),
    "section_name": ("章節名稱", "#7c3aed"),
    "llm": ("LLM Fallback", "#d97706"),
    "arbiter": ("LLM 仲裁", "#d97706"),
}

_SEC_CONTENT_CSS = """
<style>
.sec-reader {
    max-width: 52rem; margin: 0 auto; padding: 1.25rem 1.5rem;
    font-family: Georgia, "Noto Serif TC", "Source Han Serif TC", serif;
    font-size: 0.95rem; line-height: 1.75; color: #1f2937;
    background: #fafafa; border-radius: 8px;
    max-height: 560px; overflow-y: auto;
}
.sec-reader p { margin: 0 0 0.85rem 0; text-align: justify; }
.sec-reader h4 {
    color: #1e40af; font-size: 1rem; font-weight: 700;
    margin: 1.2rem 0 0.5rem 0; font-family: system-ui, sans-serif;
}
.sec-reader table {
    width: 100%; border-collapse: collapse; font-size: 0.82rem;
    margin: 0.5rem 0 1rem; font-family: system-ui, sans-serif;
}
.sec-reader td, .sec-reader th {
    padding: 0.35rem 0.6rem; border-bottom: 1px solid #e5e7eb;
}
.sec-reader ul { margin: 0.3rem 0 0.8rem 1.2rem; padding: 0; }
.sec-reader li { margin-bottom: 0.25rem; }
.tier-badge {
    display: inline-block; padding: 0.15rem 0.55rem; border-radius: 6px;
    font-size: 0.78rem; font-weight: 600; font-family: system-ui, sans-serif;
}
</style>
"""


def _render_quality_badge(item) -> None:
    """Show tier/method badge; only show numeric confidence when anomalous."""
    if item.status == ItemStatus.INCORPORATED_BY_REFERENCE:
        st.markdown(
            '<span class="tier-badge" style="background:#eef2ff;color:#4338ca;">'
            "📎 合併引用 · 已偵測</span>",
            unsafe_allow_html=True,
        )
        return
    if item.status == ItemStatus.LOW_CONFIDENCE or item.confidence < 0.9:
        st.progress(item.confidence, text=f"⚠️ 低信心：{item.confidence:.0%}")
        if item.segment_method:
            label, color = _METHOD_LABELS.get(item.segment_method, (item.segment_method, "#666"))
            st.caption(f"抽取方式：{label}")
        return
    if item.segment_method:
        label, color = _METHOD_LABELS.get(item.segment_method, (item.segment_method, "#666"))
        st.markdown(
            f'<span class="tier-badge" style="background:{color}18;color:{color};">'
            f"Tier0 · {label}</span> "
            f'<span style="font-size:0.82rem;color:#6b7280;">契約驗證通過</span>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("✓ 契約驗證通過（span integrity + token ratio）")


def _render_item(
    item,
    *,
    cik: str | None = None,
) -> None:
    icon = _status_icon(item.status)
    color = _status_color(item.status)
    name = _ITEM_NAMES.get(item.item_id, "")
    title = f"Item {item.item_id}" + (f" — {name}" if name else "")

    if item.status == ItemStatus.EXTRACTED and item.text:
        is_page_ref = is_page_reference_text(item.text)
        suffix = "（交叉引用）" if is_page_ref else ""
        with st.expander(f"{icon} {title}{suffix}", expanded=False):
            col_badge, col_len = st.columns([2, 1])
            with col_badge:
                _render_quality_badge(item)
            with col_len:
                word_count = len(item.text.split())
                st.caption(f"📝 {word_count:,} 詞 · {len(item.text):,} 字元")

            if is_page_ref:
                st.info(
                    "📄 此項目為頁碼交叉引用索引（內容散見於報表其他頁）。"
                    "請使用上方連結開啟官方原文查看完整內容。"
                )

            formatted = _format_sec_text(item.text)
            st.markdown(_SEC_CONTENT_CSS, unsafe_allow_html=True)
            st.markdown(
                f'<div class="sec-reader" style="border-left: 4px solid {color};">'
                f"{formatted}</div>",
                unsafe_allow_html=True,
            )

            if item.warnings:
                st.caption("⚠️ " + " · ".join(item.warnings))

    elif item.status == ItemStatus.INCORPORATED_BY_REFERENCE:
        with st.expander(f"{icon} {title} — 合併引用", expanded=False):
            _render_quality_badge(item)
            proxy = find_proxy_filing(cik) if cik else None
            proxy_link = ""
            if proxy:
                proxy_edgar = (
                    f"https://www.sec.gov/cgi-bin/viewer?"
                    f"action=view&cik={proxy['cik']}&accession_number={proxy['accession']}"
                    f"&xbrl_type=v"
                )
                proxy_link = (
                    f"<br>偵測到引用來源：<a href='{proxy_edgar}' target='_blank'>"
                    f"DEF 14A · {proxy['accession']}</a>（{proxy['filed']}）"
                )
            st.markdown(
                '<div style="background: #eff6ff; border: 1px solid #bfdbfe; '
                'border-radius: 8px; padding: 0.8rem 1rem; margin: 0.3rem 0;">'
                "<strong>📎 合併引用（Incorporated by Reference）</strong><br>"
                '<span style="font-size: 0.88rem; color: #444; line-height: 1.7;">'
                "此項目的完整內容引自公司的委託書（Proxy Statement / DEF 14A），"
                "而非直接列載於 10-K 正文中。此做法符合 SEC 規範。"
                f"{proxy_link}</span></div>",
                unsafe_allow_html=True,
            )
            if not proxy:
                st.caption(
                    "未找到 DEF 14A — 可在 "
                    "[EDGAR DEF 14A 搜尋](https://www.sec.gov/cgi-bin/browse-edgar"
                    "?action=getcompany&type=DEF+14A) 手動查閱。"
                )
            ref_text = None
            snippet = None
            if item.warnings:
                for w in item.warnings:
                    if w.startswith("引用原文："):
                        snippet = w.removeprefix("引用原文：")
                    elif "Incorporated" in w or "incorporated" in w or "proxy" in w.lower():
                        ref_text = w
            if snippet:
                st.caption("偵測到的引用文字：")
                st.code(snippet, language=None)
            elif ref_text:
                st.caption(f"📋 {ref_text}")
            for w in item.warnings:
                if w.startswith("引用原文：") or w == ref_text:
                    continue
                st.caption(f"📋 {w}")

    elif item.status == ItemStatus.MISSING:
        st.markdown(
            f'<div style="padding: 0.5rem 1rem; border-left: 4px solid {color}; '
            f'background: #fef2f2; border-radius: 4px; margin: 0.3rem 0;">'
            f'{icon} <strong>{title}</strong> — 報表中未找到</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="padding: 0.5rem 1rem; border-left: 4px solid {color}; '
            f'background: #f9fafb; border-radius: 4px; margin: 0.3rem 0;">'
            f'{icon} <strong>{title}</strong> — {item.status.value}</div>',
            unsafe_allow_html=True,
        )


def _format_sec_text(text: str) -> str:
    """Convert raw SEC text into readable HTML with paragraphs, headers, lists, tables."""
    import html as html_mod
    import re

    lines = text.strip().split("\n")
    parts: list[str] = []
    in_table = False
    para_buf: list[str] = []

    def flush_para() -> None:
        nonlocal para_buf
        if para_buf:
            body = " ".join(para_buf)
            parts.append(f"<p>{html_mod.escape(body)}</p>")
            para_buf = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            flush_para()
            if in_table:
                parts.append("</table>")
                in_table = False
            continue

        cols = re.split(r"  {2,}|\t{1,}", stripped)
        if len(cols) >= 3 and not stripped.startswith(("•", "-", "*", "(")):
            escaped_cols = [html_mod.escape(c.strip()) for c in cols if c.strip()]
            if len(escaped_cols) >= 3:
                flush_para()
                if not in_table:
                    parts.append("<table>")
                    in_table = True
                cells = "".join(f"<td>{c}</td>" for c in escaped_cols)
                parts.append(f"<tr>{cells}</tr>")
                continue

        if in_table:
            parts.append("</table>")
            in_table = False

        if re.match(r"^[•\-\*]\s+", stripped):
            flush_para()
            content = html_mod.escape(re.sub(r"^[•\-\*]\s+", "", stripped))
            parts.append(f"<ul><li>{content}</li></ul>")
        elif re.match(r"^\d+[\.\)]\s+", stripped):
            flush_para()
            parts.append(f"<ul><li>{html_mod.escape(stripped)}</li></ul>")
        elif stripped.isupper() and 3 < len(stripped) < 120:
            flush_para()
            parts.append(f"<h4>{html_mod.escape(stripped)}</h4>")
        elif stripped.endswith(":") and len(stripped) < 80:
            flush_para()
            parts.append(f"<h4>{html_mod.escape(stripped)}</h4>")
        else:
            para_buf.append(stripped)

    flush_para()
    if in_table:
        parts.append("</table>")

    return "\n".join(parts)


def _build_sec_markdown(result: FilingExtraction) -> str:
    lines = [f"# {result.ticker or 'N/A'} 10-K 抽取報告\n\n"]
    lines.append(f"Accession: {result.accession}\n\n")
    for item in result.items:
        name = _ITEM_NAMES.get(item.item_id, "")
        lines.append(f"## Item {item.item_id} — {name}\n\n")
        lines.append(
            f"狀態：{item.status.value}"
            + (f" | 方式：{item.segment_method}" if item.segment_method else "")
            + "\n\n"
        )
        if item.text:
            lines.append(item.text[:3000] + "\n\n---\n\n")
    return "".join(lines)


def _cache_sec_downloads(result: FilingExtraction) -> None:
    accession = result.accession or "filing"
    st.session_state["sec_download_json"] = result.model_dump_json(indent=2).encode("utf-8")
    st.session_state["sec_download_md"] = _build_sec_markdown(result).encode("utf-8")
    st.session_state["sec_download_json_name"] = f"{accession}.json"
    st.session_state["sec_download_md_name"] = f"{accession}.md"


def _log_sec_extraction(
    result: FilingExtraction | None,
    *,
    accession: str,
    html_len: int,
    label: str | None = None,
    error: str | None = None,
) -> None:
    run_id = str(uuid.uuid4())
    job_store.create_run("sec", run_id=run_id, label=label or f"SEC {accession}")
    if result is not None:
        log = {
            "accession": accession,
            "ticker": result.ticker,
            "cik": result.cik,
            "html_len": html_len,
            "extracted": sum(1 for i in result.items if i.status == ItemStatus.EXTRACTED),
            "missing": sum(1 for i in result.items if i.status == ItemStatus.MISSING),
            "incorporated": sum(
                1 for i in result.items if i.status == ItemStatus.INCORPORATED_BY_REFERENCE
            ),
            "low_confidence": sum(
                1 for i in result.items if i.status == ItemStatus.LOW_CONFIDENCE
            ),
        }
        status = "failed" if error else "success"
    else:
        log = {"accession": accession, "html_len": html_len}
        status = "failed"
    if error:
        log["error"] = error
    job_store.insert_step(
        run_id,
        0,
        action=f"extract:{accession}",
        status=status,
        log_json=json.dumps(log, default=str),
    )
    job_store.mark_run(run_id, status)


@st.fragment
def _sec_download_fragment() -> None:
    json_bytes = st.session_state.get("sec_download_json")
    if not json_bytes:
        return
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "📥 下載 JSON",
            data=json_bytes,
            file_name=st.session_state.get("sec_download_json_name", "filing.json"),
            mime="application/json",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            "📥 下載 Markdown",
            data=st.session_state.get("sec_download_md", b""),
            file_name=st.session_state.get("sec_download_md_name", "filing.md"),
            mime="text/markdown",
            use_container_width=True,
        )


def _execute_sec_extraction(
    *,
    accession: str,
    filing_url: str | None,
    ticker: str | None,
    cik: str | None,
    source: str,
    label: str | None = None,
) -> None:
    use_arbiter = True
    with st.spinner(f"正在抽取 {accession}…"):
        try:
            html, resolved_cik, source_url = fetch_filing_html(
                accession,
                url=filing_url,
                cik=cik,
                force_refresh=False,
            )
            display_cik = resolved_cik or cik
            result = extract_from_html(
                html,
                accession=accession,
                cik=display_cik,
                ticker=ticker,
                source_url=source_url or filing_url,
                use_arbiter=use_arbiter,
                run_id=None,
            )
            st.session_state["sec_result"] = result
            st.session_state["sec_result_accession"] = accession
            st.session_state["sec_result_source"] = source
            st.session_state["sec_html_len"] = len(html)
            _cache_sec_downloads(result)
            _log_sec_extraction(
                result,
                accession=accession,
                html_len=len(html),
                label=label,
            )
        except Exception as exc:
            err_msg = str(exc)
            st.error(f"❌ 抽取失敗：{err_msg}")
            _log_sec_extraction(
                None,
                accession=accession,
                html_len=st.session_state.get("sec_html_len", 0),
                label=label,
                error=err_msg,
            )
            if "CIK" in err_msg or "404" in err_msg or "index" in err_msg.lower():
                st.info(
                    "💡 **常見原因**：\n"
                    "1. Accession number 格式不正確（需含連字號，如 `0000950170-24-087843`）\n"
                    "2. 該報表的 CIK 無法自動解析 — 請在上方填入公司的 CIK\n"
                    "3. 直接貼上完整的 EDGAR 報表 URL 可以跳過 CIK 解析"
                )


@st.fragment
def _sec_summary_fragment(result: FilingExtraction) -> None:
    extracted = sum(1 for i in result.items if i.status == ItemStatus.EXTRACTED)
    incorporated = sum(1 for i in result.items if i.status == ItemStatus.INCORPORATED_BY_REFERENCE)
    missing = sum(1 for i in result.items if i.status == ItemStatus.MISSING)
    low_conf = sum(1 for i in result.items if i.status == ItemStatus.LOW_CONFIDENCE)
    total = len(result.items) or 1
    covered = extracted + incorporated
    pct = covered / total

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("✅ 已抽取", extracted)
    c2.metric("📎 合併引用", incorporated)
    c3.metric("⚠️ 低信心", low_conf)
    c4.metric("❌ 缺失", missing)
    c5.metric("📊 總計", len(result.items))

    st.markdown(
        f'<div style="background:#f3f4f6;border-radius:8px;padding:0.55rem 0.85rem;'
        f'margin:0.35rem 0 0.75rem;font-size:0.9rem;color:#374151;">'
        f"涵蓋率：<strong>{covered}/{total}</strong> 項已解析 "
        f"(<strong>{pct:.0%}</strong>)</div>",
        unsafe_allow_html=True,
    )
    _sec_download_fragment()


def _render_sec_results(result: FilingExtraction) -> None:
    if st.session_state.get("sec_download_json") is None:
        _cache_sec_downloads(result)

    st.divider()
    html_len = st.session_state.get("sec_html_len", 0)
    filing_viewer = build_sec_viewer_url(result.accession, cik=result.cik)
    doc_link = ""
    if result.source_url:
        doc_link = (
            f' &nbsp;|&nbsp; <a href="{result.source_url}" target="_blank">原始文件</a>'
        )
    st.markdown(
        f'<div style="background: linear-gradient(135deg, #eff6ff 0%, #f0fdf4 100%); '
        f'border-radius: 12px; padding: 1.2rem; margin-bottom: 1rem;">'
        f'<strong style="font-size: 1.3rem;">{result.ticker or "N/A"}</strong> &nbsp;'
        f'<span style="color:#666;">CIK: {result.cik or "N/A"} &nbsp;|&nbsp; '
        f'Accession: {result.accession}</span><br>'
        f'<span style="font-size: 0.85rem; color: #888;">'
        f'Source: {html_len:,} chars HTML &nbsp;|&nbsp; '
        f'<a href="{filing_viewer}" target="_blank">SEC 互動式檢視器</a>'
        f'{doc_link}</span></div>',
        unsafe_allow_html=True,
    )

    _sec_summary_fragment(result)
    st.divider()

    by_part: dict[str, list] = {p: [] for p in _PART_ORDER}
    by_part["Other"] = []
    for item in result.items:
        part = item.part or "Other"
        by_part.setdefault(part, []).append(item)

    for part in _PART_ORDER + (["Other"] if by_part.get("Other") else []):
        items = by_part.get(part) or []
        if not items:
            continue
        st.markdown(f"### Part {part}")
        for item in items:
            _render_item(item, cik=result.cik)


def _maybe_render_sec_results(*, source: str, accession: str) -> None:
    if not sec_result_matches_context(
        source=source,
        accession=accession,
        result_source=st.session_state.get("sec_result_source"),
        result_accession=st.session_state.get("sec_result_accession"),
    ):
        return
    result = st.session_state.get("sec_result")
    if result:
        _render_sec_results(result)


# --- Page Layout ---

st.markdown(
    '<h1 style="margin-bottom:0;">📄 SEC 10-K 結構化抽取</h1>',
    unsafe_allow_html=True,
)
st.caption(
    "混合管線：Tier0（BS4 + 正則分段）→ 跨度完整性驗證 → "
    "LLM 仲裁（低信心段落自動調整邊界）"
)

tab_manifest, tab_custom = st.tabs(["📋 已註冊報表", "🔗 自訂報表"])

with tab_manifest:
    filings = _load_manifest()
    labels = [f"{f['ticker']} — {f['accession']} ({f.get('label', '')})" for f in filings]
    choice = st.selectbox("選擇報表", labels, index=0)
    selected = filings[labels.index(choice)]
    if st.button("🚀 開始抽取", type="primary", use_container_width=True, key="run_manifest"):
        _execute_sec_extraction(
            accession=selected["accession"],
            filing_url=selected.get("url"),
            ticker=selected.get("ticker"),
            cik=selected.get("cik"),
            source="manifest",
            label=f"{selected.get('ticker', 'SEC')} 10-K",
        )
    _maybe_render_sec_results(source="manifest", accession=selected["accession"])

with tab_custom:
    st.markdown(
        "**建議使用美股代碼**（如 `MSFT`、`GOOGL`）或公司法定英文名；"
        "避免單字如 `google`（會搜到報表內文，易誤判）。"
        "已知 Accession 可直接貼上，最精準。"
    )

    col_search, col_btn = st.columns([3, 1])
    with col_search:
        search_query = st.text_input(
            "🔍 搜尋公司",
            placeholder="建議：MSFT / GOOGL / Alphabet / 0000950170-24-087843",
            label_visibility="collapsed",
        )
    with col_btn:
        do_search = st.button("搜尋", use_container_width=True)

    if do_search and search_query.strip():
        q = search_query.strip()
        hint = search_quality_hint(q)
        if hint:
            st.info(hint)
        with st.spinner("搜尋 EDGAR…"):
            hits = search_filings(q)
        st.session_state["edgar_search_results"] = hits
        st.session_state["edgar_search_query"] = q
        if not hits:
            st.warning(
                "未找到可識別的 10-K 報表。請改用 **ticker**（如 GOOGL 而非 google）、"
                "公司英文名，或直接輸入 Accession Number。"
            )

    search_results = st.session_state.get("edgar_search_results", [])
    if search_results:
        st.caption("請確認 **公司全名、ticker、accession、申報日期** 後再使用。")
        search_labels = [format_filing_search_label(r) for r in search_results]
        search_choice = st.selectbox("選擇報表", search_labels, key="search_select")
        chosen = search_results[search_labels.index(search_choice)]
        st.markdown(
            f"**已選：** {chosen.get('company', '—')} · "
            f"**{chosen.get('ticker') or '—'}** · `{chosen['accession']}` · {chosen.get('filed', '')}"
        )
        if st.button("📄 使用此報表", use_container_width=True, key="use_search_result"):
            st.session_state["custom_acc_fill"] = chosen["accession"]
            st.session_state["custom_cik_fill"] = chosen["cik"]
            st.session_state["custom_ticker_fill"] = chosen.get("ticker", "")
            st.success(
                f"已填入 {chosen.get('company')} ({chosen.get('ticker') or '—'}) 的 accession。"
                "請在下方確認後按「開始抽取」。"
            )

    st.divider()
    st.markdown("或直接輸入 Accession Number：")

    custom_accession = st.text_input(
        "Accession Number",
        value=st.session_state.get("custom_acc_fill", ""),
        placeholder="例：0000950170-24-087843",
        help="格式：XXXXXXXXXX-YY-ZZZZZZ（含連字號）",
    )
    col_cik, col_ticker = st.columns(2)
    with col_cik:
        custom_cik = st.text_input(
            "CIK（選填，建議填寫）",
            value=st.session_state.get("custom_cik_fill", ""),
            placeholder="例：789019（微軟）",
            help="公司的 CIK 編號。若不填，系統會自動從 EDGAR 查詢。",
        )
    with col_ticker:
        custom_ticker = st.text_input(
            "股票代碼（選填）",
            value=st.session_state.get("custom_ticker_fill", ""),
            placeholder="MSFT",
        )
    custom_url = st.text_input(
        "報表 URL（選填，留空自動解析）",
        placeholder="https://www.sec.gov/Archives/edgar/data/.../filing.htm",
    )
    if st.button("🚀 開始抽取", type="primary", use_container_width=True, key="run_custom"):
        if not custom_accession.strip():
            st.error("請輸入 Accession Number。")
        else:
            _execute_sec_extraction(
                accession=custom_accession.strip(),
                filing_url=custom_url.strip() or None,
                ticker=custom_ticker.strip() or None,
                cik=custom_cik.strip() or None,
                source="custom",
                label=f"{custom_ticker.strip() or custom_accession.strip()} 10-K",
            )
    _maybe_render_sec_results(source="custom", accession=custom_accession.strip())
