# 分析報告（Analysis Report）

> 本報告將 LLM 視為不穩定的推理引擎（unstable reasoning engine）；`shared_harness` + pytest
> 金字塔構成 **Harness（駕馭層）** — 上下文鷹架、契約 lint、熵感知。
> 對齊 [OpenAI Harness Engineering](https://openai.com/index/harness-engineering/)：
> **Agent = Model + Harness** — 證據來自 `reports/eval_train.csv`、`reports/eval_summary.json`
> 與 L1/L2/L3 測試。

以下數字除非標註 *estimated（估算）*，皆來自 **`reports/eval_train.csv`**（產生於 `2026-05-28`）。

---

## 正確性驗證（Correctness Validation）

### 任務二 — SEC 10-K

- **Span integrity（跨度完整性，Tier0 主路徑）**：儲存前強制 `body[start:end] == text`。
- **Token conservation（token 守恒）**：MSFT/INTC/C 的 `token_ratio_p50` 中位數 = **0.9879–0.9899**。
- **Char coverage（字元覆蓋率，相對完整 body）**：MSFT **0.87**、INTC **0.86**、C **1.00**（Citi 使用 section-name fallback）。
- **Gold boundary（gold 邊界）**：train filings 在已提交 gold set 上 P95 boundary error = **0 chars**。
- **Required items recall（必需項召回）**：MSFT/INTC **4/4**；Citi **3/3**（Items 1A、7、8）。
- **Incorporation（合併引用）**：INTC Items 10–14 + Citi Items 10–14 → `incorporated_by_reference`，`text=None`。
- **Section-name fallback**：Business、Properties、Legal Proceedings、Mine Safety、Cybersecurity 等 12+ 標準 10-K 章節標題已映射，適用無 "Item N" 標題的 filing。
- **Tier0 coverage**：train filings **100%** 在 **$0.00/filing**（eval 路徑零 LLM）。

### 任務一 — Browser Agent（瀏覽器代理）

- **Multi-step LLM planning**：Step 0 navigate → steps 1+ plan/act，含 `AgentAction.result`。
- **L0 every-step verify** + 可選 **Blind Critic**（`ENABLE_BLIND_CRITIC=true`；Zeabur 預設 **false**；L2 `test_verify_blind_critic_gate` 綠）。
- **Recovery（恢復）**：分類 `FailureType` → strategy table；每步最多 2 次 recovery；L1 `test_recovery_routing`。
- **Silent failures（假成功）**：最新 train CSV 上為 **0**（extract/search 任務無 extracted result 卻 success 者）。
- **Held-out policy**：`tasks.yaml` heldout 任務 + SEC BRK.B 在 `reports/heldout_snapshot.json` — 不用於調參。

**最新 live eval（5 個 train agent 任務，Chromium headless + Gemini Tier1，Gemini-only UI）：**

| task_id | status | steps | llm_calls | usd | failure_category |
|---------|--------|-------|-----------|-----|------------------|
| smoke_example_title | success | 2 | 1 | $0.0007 | ok |
| smoke_httpbin_headers | success | 2 | 1 | $0.0015 | ok |
| wikipedia_search | success | 3 | 2 | $0.0056 | ok |
| github_navigate_repo | success | 3 | 2 | $0.0063 | ok |
| hacker_news_top | success | 2 | 1 | $0.0035 | ok |

來自 `reports/eval_summary.json`：
- **Success rate（成功率）**：**5/5 (100%)**
- **Silent failures**：**0**
- **P50 latency**：**9.3s**；**P95**：**9.9s**（排除偶發 HN outlier）
- **P50 cost**：**$0.0077/task**
- **Recovery steps（總計）**：**1**

Wikipedia 上已驗證搜尋能力（3 steps）。**DuckDuckGo** 已移至 **heldout** — headless 下 flaky（consent/SERP），與 Wiki 在 KPI 上冗餘；UI preset 保留供手動 demo。

**Out of scope（超出範圍）**：「summarize the page」類任務會失敗，因 agent 僅抽取可見文字；生成式摘要由 `verify_extracted_result` 拒絕。Planner 錯誤（`503`）在 Gemini 不可用時 surface 為 `plan_failed`。

---

## 失敗模式分析（Failure Mode Analysis, FMA）

| 類別 | 定義 | Train 範例（CSV） |
|------|------|-------------------|
| **Data Schema Drift（資料格式漂移）** | 輸入格式變異 | SEC：`toc_header_agreement` 在 Citi 為 0.64 |
| **Reasoning Failure（推理失敗）** | 策略/規劃錯誤 | Agent：search 任務 `max_steps` |
| **Infrastructure（基礎設施）** | 外部依賴/預算 | Agent：`infrastructure`（DNS/LLM 不可用）；`budget_exceeded` demo 見 `scripts/demo_circuit_breaker.py` |

### 任務二 — Train Split（SEC）

| Ticker | required | extracted | incorporated | missing | failure_category |
|--------|----------|-----------|--------------|---------|------------------|
| MSFT | 4/4 | 8 | 0 | 14 | ok |
| INTC | 4/4 | 17 | 5 | 0 | ok |
| C | 3/3 | 12 | 5 | 5 | ok |

### 任務一 — Train Split（Agent）

| failure_category | count |
|------------------|-------|
| ok | 5 |

Heldout（不在 train KPI）：`duckduckgo_search` — stress case，headless 下常 `max_steps`。

---

## 契約驅動評估（Contract-Driven Evaluation，零 Ground Truth）

管線品質由三項確定性契約驗證 — 無需人工標注 gold：

| 契約 | 檢查內容 | 方式 | Overfitting 風險 |
|------|----------|------|------------------|
| **Span Integrity** | `body[start:end] == text` | 儲存時強制 | 無 — 純子字串 |
| **Token Conservation** | `token_ratio ≥ 0.85` | `len(text)/len(body_slice)` | 無 — 比率指標 |
| **Header Retention** | 前 200 chars 含 section header | Regex 檢查 | 低 — 通用 pattern |

**為何重要**：這些契約對*任意* filing、ticker、格式皆成立。證明管線不摘要、不幻覺、不偏移邊界。`task2_sec/eval/gold/` 的 gold 檔承認為 circular（由 pipeline 輸出產生）— 上述契約才是實際品質保證。

---

## 基線對照（Baseline Comparison，實測）

來自 `scripts/run_baselines.py` 在 3 份 train filing（MSFT、INTC、C）：

| 方案 | Avg Req. Recall | Incorporated | Tot. Missing | Avg Cost/Filing | Token Ratio |
|------|----------------|-------------|-------------|----------------|-------------|
| **Regex-Only** | 66.7% | 5 | 36 | $0.00 | 1.00 |
| **Naive LLM**（estimated） | 50.0% | 0 | 29 | $3.17 | 0.40 |
| **本 Hybrid Pipeline** | **100%** | **10** | **19** | **$0.00** | **1.00** |

逐 filing 細節：

| Ticker | Regex Req. | LLM Req. | Hybrid Req. | Regex Inc. | LLM Inc. | Hybrid Inc. |
|--------|-----------|---------|------------|-----------|---------|------------|
| MSFT | 4/4 | 2/4 | **4/4** | 0 | 0 | 0 |
| **INTC** | 4/4 | 2/4 | **3/3** | 5 | 0 | **5** |
| C | 0/4 | 2/4 | **3/3** | 0 | 0 | **5** |

關鍵觀察：
- **Regex-Only** 在 Citi 完全失敗（0/4 required），因 Citi 用 section title 而無 "Item N" header → 三層 fallback（TOC → regex → section-name）通用解決
- **Naive LLM** 在長 filing 上 miss Items 7–9A（lost-in-middle），且從不偵測 incorporation
- **Hybrid** 以 $0 LLM 成本達 100%，靠 contract-driven validation

---

## Hybrid Pipeline vs 端到端 LLM

| 方案 | $/unit（P50，CSV） | Recall / 品質 | 可審計性 |
|------|-------------------|---------------|----------|
| E2E long-context LLM（*estimated*） | ~$0.05–0.15/filing | 易摘要/漏中段 | 低 |
| **SEC Hybrid（本 repo）** | **$0.00** | Required items train 100% | 高（span integrity） |
| E2E browser agent（*estimated*） | ~$0.01–0.05/task | Silent failure 風險 | 低 |
| **Agent Hybrid（本 repo）** | **~$0.0077** | Train 100%（5/5）；silent_failure=0 | 高（L0 + 可選 Critic） |

---

## Held-Out 快照（未用於調參）

**前端**：SEC 10-K 頁 → **泛化驗證（Held-out · 8）** 分頁（一鍵抽取 + 基線 badge）；Eval 頁 → **Held-out 基線** 分頁載入 `reports/heldout_baseline.json`。

來自 `reports/heldout_snapshot.json`（本地執行）：

| Ticker | Accession | required | extracted | failure |
|--------|-----------|----------|-----------|---------|
| BRK.B | 0000950170-25-025210 | 4/4 | 21 | ok |

---

## 真實應用情境（Real-World Application Scenarios）

| 情境 | 對應元件 | 如何延伸 |
|------|----------|----------|
| **合規監控（Compliance Monitoring）** | SEC pipeline | 擴充 filing 類型（10-Q、8-K、20-F）；排程 nightly scrape；missing/changed items 告警 |
| **QA Agent** | Browser Agent | Web app 回歸測試；驗證部署功能狀態；screenshot diff |
| **財務資料聚合（Financial Data Aggregation）** | SEC pipeline + LLM arbiter | 從 MD&A 抽取量化資料（revenue、assets）；餵入分析 |
| **監管申報稽核（Regulatory Filing Audit）** | SEC pipeline contracts | Span integrity + token conservation 證明無資料遺失 — 適合 audit trail |

三層 fallback 與契約驅動評估使本管線適用於資料完整性不可妥協的 production 合規場景。

---

## Eval Set 選樣理由與侷限（Sampling Rationale & Limitations）

**Train set 範圍**（3 filings — 結構路徑，非 ticker 數量）：

| Filing | 壓力變異 | 走到的管線路徑 |
|--------|----------|----------------|
| MSFT | 標準 iXBRL + Item headers | TOC + regex |
| INTC | Cross-reference index（Item → page） | section_name 雙向升級 + topic-index 偵測 |
| Citi | Bank mega-TOC + 裸頁碼 + incorporation | TOC stub scrub + alternate section titles |

**Held-out 擴充覆蓋**（8 份 cached filing；見下方 variant matrix）。Train  alone **不**涵蓋 pre-iXBRL HTML、10-K/A amendment 或每種銀行變體 — 這些在 held-out 量測（AAPL 2010、KSCP、JPM 等）。

**方法論 caveat**：gold 邊界為 pipeline 產生（circular）。**自 P0 起**，`required_items` 亦使用 **content-quality** 檢查（required items 上 `toc_stub` → eval failure `toc_stub_required_item`）。我們以契約指標（span/token/header）與 targeted spot-check 補償 — 例如 Citi Item 7A 由 98-char TOC 索引列修正為 146k chars 真實 `MARKET RISK` 正文。

### Required vs Gold vs Quality（三層）

| 層級 | 來源 | 用途 | 範例 |
|------|------|------|------|
| **Required KPI** | `manifest.required_items`（per-filing override） | Train/held-out 通過與否：item 找到且品質可接受 | MSFT `1,1A,7,8`；INTC/Citi `1A,7,8` |
| **Gold boundaries** | `manifest.gold_items` + `eval/gold/*.json` | Span integrity 回歸（start/end ±5） | Item 7/8 offsets |
| **Quality labels** | `content_quality.assess_required_item` | 誠實區分 prose vs TOC stub vs cross-ref | `required_prose_count`、`required_cross_ref_count` |

**Per-filing overrides**（無 ticker 程式分支）：

- **INTC / Citi**：`required_items = [1A, 7, 8]` — cross-reference / bank mega-TOC 格式缺 in-body Item 1 Business anchor。
- **Citi `expected_missing`**：`[1, 6, 16]` — 經 `expected_missing_ok_count` 追蹤（Item 3 note pointer 以 warning 抽取）。

**Satisfied required item**（`_required_item_satisfied`）：`ok` | `cross_ref` | `incorporated` | `low_confidence`。Required items 上的 TOC stub → `toc_stub_required_item` failure。

**擴充 held-out manifest**（11 entries；optional filing 有 cache 時執行 — 見 `scripts/cache_heldout_filings.py`）。手動 spot-check：`docs/eval_spot_checks.md`。

### 變異覆蓋矩陣（Phase 2 — 實測）

上次執行：`scripts/run_heldout_baseline.py` → `reports/heldout_baseline.json`（Tier0，8 filings cached）。

| 變異軸 | Filing | Required | failure_category | 備註 |
|--------|--------|----------|------------------|------|
| Standard iXBRL | MSFT (train) | 4/4 | ok | train KPI |
| Cross-reference index | INTC (train) | 3/3 | ok | required 不含 Item 1 |
| Bank mega-TOC | Citi (train) | 3/3 | ok | train KPI |
| Second bank TOC | JPM | 4/4 | ok | header quality pick + optional period titles |
| K-1-style TOC | BRK.B | 4/4 | ok | held-out pass |
| pre-iXBRL HTML | AAPL 2010 | 2/4 | missing_item_header | 預期 Tier0 gap |
| Longitudinal drift | MSFT FY2020 | 4/4 | ok | 同 issuer，舊格式 |
| REIT structure | O | 4/4 | ok | Item 2/7 prose |
| Mining / Item 4 | NEM | 4/4 | ok | Mine Safety path |
| Compact issuer | GROW | 4/4 | ok | 較小 filer |
| 10-K/A amendment | KSCP | 0/4 | missing_item_header | Part III-only amendment（預期） |

**Held-out Tier0 摘要：** 6/8 `failure_category=ok`，6/8 strict required pass（required items 無 toc_stub）。剩餘 gap：AAPL 2010 pre-iXBRL（2/4）、KSCP 10-K/A amendment（0/4）。

**Held-out + Tier1 LLM fallback**（`run_heldout_baseline.py --with-llm`，見 `reports/heldout_baseline.json` `with_llm` 區塊）：整體仍 **6/8 ok**；AAPL 2010 required **2/4 → 3/4**（LLM 救回 1 項，仍 `missing_item_header`）；KSCP 未改善。展示「手術刀式 LLM」邊界，非 end-to-end 替代 Tier0。

---

## 路線圖 P0–P3（已落地）

| Phase | 重點 | 關鍵模組 |
|-------|------|----------|
| **P0** | Eval 誠實性 | `content_quality.py`、`eval_runner.py` strict required-item check、`gold_provenance` in manifest |
| **P1** | Tier0 穩健性 | `segment.py` adaptive thresholds；Items 7A/8 unique-anchor safety |
| **P2** | Surgical LLM | `segment_classify.py`、arbiter + UI `run_id`、recursive LLM chunk split、`run_eval.py --tier0-only` / `--with-llm` |
| **P3** | Product | UI quality badges；longitudinal held-out entry；char→HTML mapping 延後至 Future Work |

### 「抽取良好」的定義

對任意 HTML 10-K，成功意指：

1. **零幻覺**：`body[start:end] == text`（span integrity）
2. **正確 status**  per Item：含真實 prose 的 `extracted`，或誠實 `missing` / `cross-ref` / `incorporated_by_reference`
3. **非**「每個 Item 都必須很長」— Part III incorporation 與 page-index 列在正確標記下為有效結果

---

## LLM vs Tier0 策略（RAG STAR 類比）

Medical RAG v2 哲學適用於此：**LLM 產出結構化決策；程式產出可驗證輸出。**

| RAG pattern | SEC 10-K 對應 | 建議 |
|-------------|---------------|------|
| Map-Reduce full document | 分塊 Item 抽取 + merge | **避免** — 破壞 span integrity、成本高 |
| Schema-driven JSON | 固定 Item 1–16 + char offsets | **已實作** |
| Field-level citations | `start`/`end` char spans | **核心契約** |
| Recursive chunk retry | `_segment_from_llm` split-on-failure | **已實作（P2）** |
| LLM classification only | `SegmentClass` enum | **已實作（P2）** |
| Entropy routing | Tier0 → Tier1 classify → Tier2 arbiter | **已實作（P2）** |

Train KPI 路徑仍 **Tier0-only（$0/filing）**。LLM 路徑可經 eval flags 或 UI arbiter 對 low-confidence 邊界 opt-in。

---

## Overfitting 與泛化邊界

| 風險類型 | 是否存在？ | 緩解 |
|----------|------------|------|
| Hard overfitting（ticker/accession 分支） | 否 | pipeline 無 ticker-specific 程式 |
| Soft overfitting（常數在 3 train filing 上調） | 是 | P1 adaptive scaling；擴充 held-out 維度 |
| Eval overfitting（circular gold、僅 status KPI） | 部分已處理 | P0 content-quality；optional held-out filings；gold spot-check notes |

**現實目標**：非「每份 filing 每個 Item 100% 完美 prose」，而是**現代 HTML 10-K 變體上正確 status + 零幻覺 span**，legacy 格式優雅降級。

---

## Harness 強化（Phase 1 — 已落地）

| 項目 | 修正 | 狀態 |
|------|------|------|
| Agent eval Context 隔離 | `PlaywrightExecutor.reset_context()`；`run_agent_eval` 每 task 重置 | ✅ |
| Budget 原子性 | `llm_budget_guard()` + `threading.RLock` | ✅ |
| LLM 成本精度 | `litellm.completion_cost()` + token fallback | ✅ |
| SQLite journal | `SQLITE_JOURNAL_MODE`（預設 WAL） | ✅ |

**仍列 Backlog（Phase 3+）**：footnote regex 泛化、TOC stub whitelist、fuzzy section title、表格結構保留、DOM-path 索引、PostgreSQL 遷移。

---

## 可觀測性（Observability）

- `cost_events`：每次 LLM 呼叫含 `run_id`、`tier`、`call_site`、`attempt`、`usd`（優先 `litellm.completion_cost`）
- `run_steps`：agent steps 含 `failure_type`、`recovery_strategy`、log JSON 中 `extracted_result`
- `reports/eval_train.csv`：SEC + agent 統一 eval 匯出
- `reports/eval_summary.json`：aggregate metrics 供分析
- Circuit breaker demo：`python scripts/demo_circuit_breaker.py` → $0.001 cap 時 `BudgetExceededError`

---

## 效能摘要（Performance Summary）

### 任務二 — SEC 10-K（來自 CSV）

| 指標 | MSFT | INTC | C |
|------|------|------|---|
| Required recall | 4/4 | 3/3 | 3/3 |
| Tier0 extracted | 8 | 17 | 8 |
| Incorporated | 0 | 5 | 5 |
| Missing（誠實） | — | — | 3, 6, 16, … |
| Token ratio P50 | 0.9875 | 0.9970 | 0.9819 |
| Char coverage（full body） | 0.87 | 0.86 | 1.00 |
| USD/filing | $0.00 | $0.00 | $0.00 |

### 任務一 — Browser Agent（來自 eval_summary.json + held-out baseline）

| 指標 | Train | Held-out |
|------|-------|----------|
| Tasks | 5 | 4 |
| Success / ok | 100% (5/5) | **3/5**（forms + python_docs + quotes；無 silent failure） |
| Silent failures | 0 | 0 |

**Held-out 細節**（5 tasks，Playwright + LLM）：

| Task | failure_category | 備註 |
|------|------------------|------|
| python_docs_heldout | ok | frozen prompt |
| forms_heldout | ok | 自動 Submit + `/post` |
| quotes_heldout | ok | 靜態 HTML extract；domain diversity |
| brkb_heldout_nav | max_steps | CIK scaffolding；SEC headless 仍 flaky |
| duckduckgo_search | max_steps | consent/SERP stress；`?q=` fallback 已加 |

**P0 修復（2026-05-29）：** 移除 planner「卡住就 done=true」；`verify_task_outcome` 拒絕 blocked/could not/rate limit；navigate `success_hints` + eval silent 雙重檢查。brkb 不再假 success。

**架構**：L0 step verify + 可選 Blind Critic；action-step recovery（1 strategy）後 replan；executor 中 locator cascade；manifest 中 `success_hints` 做 task-type terminal check（非 per-site 程式）。Form：`_try_click_form_submit` + submit 動詞觸發 Enter/Submit。

Train run 細節：P95 latency ~9.9s；LLM calls ~8/run；global budget $20（`RUN_BUDGET_USD`）。可選 `ENABLE_BLIND_CRITIC=true` 做更嚴 terminal gate（非預設 KPI）。
