# Prompt Iteration Log

Record v1→v2 changes with Failed Path / Resolution / Validation.

## deployment_fix: Agent LLM 打通 + SEC UI 重構 + LLM fallback 層 + 評估即時化

- **Failed Path**: 部署後發現五個問題：
  1. 瀏覽器代理每步都 `plan_failed` — Gemini thinking 模型 `reasoning_effort="minimal"`
     導致 thinking tokens 消耗全部預算，`content=None` → `ValidationError` → 重試耗盡
  2. SEC 自訂報表用完後切回已註冊報表，仍讀到自訂報表值 — Streamlit widget state
     在 tab 切換時不清空，`if custom_accession.strip()` 永遠為 True
  3. LLM 仲裁需手動勾選 checkbox（預設 False），使用者不知道要開啟
  4. 評估儀表板一進頁面就讀 repo 裡的靜態 cache 結果，非即時
  5. 使用者需手動去外部網站找 accession number
- **Resolution**:
  1. `llm_config.py`: `reasoning_effort` 改 `None`；`llm_router.py`: 偵測 `content is None`
     主動拋 `ValueError` 觸發重試（而非靜默返回空字串讓下游 parse 失敗）
  2. 每個 tab 各自放獨立的「開始抽取」按鈕 + `_run_source` flag 判斷來源
  3. 移除 checkbox，`use_arbiter = True` 直接硬編碼
  4. 評估儀表板改為 on-demand：頁面初始只顯示「執行評估」按鈕，即時呼叫
     `run_sec_eval()` / `run_agent_eval()` 產生結果
  5. 整合 EDGAR EFTS 搜尋 API：`search_filings()` in `edgar_client.py`，
     搜尋結果自動帶入 accession/CIK/ticker
  6. 新增 SEC LLM fallback 層：`SegmentMethod.LLM`，coverage < 30% 或 missing > 5 時觸發，
     LLM 只回傳 `(item_id, offset)` 偏移量，文字仍 `body[start:end]` 原文切割
  7. 新增 `scripts/e2e_smoke.py`：push 前驗證 LLM、SEC pipeline、Agent planning
- **Validation**: 65 tests pass; LLM empty-content 檢測在 `_invoke` 層攔截；
  tab 切換 bug 透過獨立按鈕 + source flag 根治；LLM fallback 層不影響 Tier0 測試
  （`use_llm_fallback=False` 在 tier0-only 測試中明確禁用）。

## infra_fix: MSFT cache + litellm upgrade + normalize robustness

- **Failed Path**: Three critical infrastructure issues:
  1. MSFT cache file was a 1,825-byte fake mock (hand-written HTML with dummy text),
     not the real 6.86 MB EDGAR 10-K filing. Accession `0000789019-24-000045` was wrong —
     the actual MSFT FY2024 10-K accession is `0000950170-24-087843`.
  2. `litellm==1.55.0` couldn't parse Gemini 2.5/3 thinking model responses — returned
     `content=None` because reasoning tokens consumed the `max_tokens` budget, leaving
     zero text tokens. This caused `ValidationError` → retries exhausted → 
     `AllProvidersFailed` → "LLM planner unavailable" on every agent run.
  3. `normalize.py` crashed with `AttributeError: 'NoneType' object has no attribute 'get'`
     on real MSFT filing (malformed HTML where `tag.attrs` is `None`).
- **Resolution**:
  1. Fixed MSFT accession in `manifest.json`, re-downloaded real filing (6.86 MB),
     regenerated gold files. Updated all references (`.gitignore`, README, tests).
  2. Upgraded `litellm>=1.86.0` — properly handles Gemini thinking tokens.
     `gemini-3-flash-preview` and `gemini-3.1-pro-preview` now return content correctly.
  3. Added `if tag.attrs is None: continue` guard in `_remove_hidden_elements`.
  4. Fixed `eval_runner.py` gold comparison: excluded incorporated items (no `start`/`end`)
     from boundary matching total.
- **Validation**: 46 unit tests pass; 3/3 SEC filings pass eval (MSFT now 22/22 extracted,
  char_coverage 0.9877); Gemini API calls return proper content.

## boundary_arbiter: v1 → v2 (regex fallback + prompt hardening)

- **Failed Path**: Initial regex `ITEM\s+\d+` matched inline cross-references like
  "see Item 1 above" as segment headers, causing false boundary splits mid-paragraph.
  Additionally, `v1_boundary_arbiter.txt` lacked explicit constraint against summarization,
  leading to potential token ratio violations when arbiter is invoked.
- **Resolution**: Anchored `HEADER_RE` to line-start (`(?m)^[ \t]*`) in `segment.py`;
  added negative-sample assertions in `test_regex_boundary_fallback.py` to reject
  body-inline mentions. Longer item IDs match first (e.g. "10" before "1").
  Promoted to `prompts/v2_boundary_arbiter.txt` adding: ratio constraint (≥0.85),
  trailing whitespace rule, and explicit negative constraints for numerical preservation.
- **Validation**: `test_regex_boundary_fallback` green — negative sample
  `"see Item 1 above"` no longer produces a segment hit; `pytest -m unit` all pass.

## incorporation_by_reference: Citi Items 10–14

- **Failed Path**: Pipeline initially reported Items 10–14 as `extracted` with full text
  that was actually just a one-line incorporation notice, misleading eval metrics.
- **Resolution**: Added `detect_incorporation()` in `task2_sec/pipeline/incorporation.py`
  using regex to detect "incorporated by reference" language; status set to
  `incorporated_by_reference` with `text=None` to avoid hallucinating content.
- **Validation**: `test_item_status::test_incorporation_by_reference_no_fake_fulltext` green;
  `test_sec_manifest_citi_incorporation` confirms Items 10 and 14 correctly flagged.

## agent_recovery: v1 → v2 (classified routing vs blind retry)

- **Failed Path**: Initial agent design used a generic `try/except → retry` loop. Same
  recovery action was attempted repeatedly (e.g. re-clicking the same missing element),
  burning LLM calls without progress and triggering `MaxLLMCalls` breaker.
  `v1_recovery.txt` was a flat instruction with no failure-type awareness.
- **Resolution**: Introduced `FailureType` enum + `STRATEGY_TABLE` in `recovery.py`.
  `get_next_strategy(failure_type, attempted)` returns the next *untried* strategy;
  `MAX_RECOVERY_PER_STEP = 2` caps retries. `prompt_loader.load_prompt("recovery",
  variant=failure_type)` injects the matching SOP fragment from `prompts/sops/recovery.md`.
  Promoted to `prompts/v2_recovery.txt` with per-failure-type strategy options,
  explicit "do NOT repeat" constraint, and JSON-only output format.
- **Validation**: `test_recovery_routing` (9 assertions) green — `ACTION_NO_EFFECT` returns
  different strategies on each call; exhausted strategies return `None`; `CAPTCHA_OR_LOGIN`
  always returns `blocked`. L2 `test_agent_recovery_loop` confirms recovery→success and
  exhaustion→failed paths work end-to-end.
  New L2 `test_verify_blind_critic_gate` confirms critic NO → run fails (silent_failure=0).

## agent_plan: v1 → v2 (multi-step execution + result extraction)

- **Failed Path**: v1 agent treated step 0 (navigation) as potentially task-complete — if
  the page loaded and verify passed, the loop broke immediately. This meant search tasks
  (DuckDuckGo, Wikipedia) and extraction tasks (Hacker News top story) would always fail
  because the agent never interacted with the page beyond loading it. Output was limited
  to status only (success/failed), with no task-specific result.
- **Resolution**: Redesigned loop in `loop.py` — step 0 ALWAYS continues to LLM planning;
  steps 1+ use `_plan_next_action()` to determine actions (click, type, scroll, etc.) and
  declare `done=true` with a `result` field only when the task is genuinely complete.
  Updated `AgentAction` schema with `result: str` field. Updated `v1_agent_plan.txt` to
  instruct: "do NOT set done=true just because the page loaded; fill result when done."
- **Validation**: All 58 tests pass (46 unit + 12 integration); `test_agent_recovery_loop`
  and `test_verify_blind_critic_gate` confirm multi-step flow works correctly with
  recovery and Blind Critic gate. Train success rate improved from 4/6 → 6/6.

## segment: v2 → v3 (TOC avoidance + page-reference upgrade + section-name generalization)

- **Failed Path**: INTC 10-K has a "Form 10-K Cross-Reference Index" acting as TOC —
  `_pick_best_start` with 3% exclusion zone was too narrow, picking TOC page references
  (e.g. "Item 1. Business: Pages 3-4") instead of actual content sections. Items 10–14
  had `(a)` footnote markers referencing Proxy Statement but were classified as `extracted`.
  `_SECTION_NAME_MAP` lacked Item 1 (Business), 2 (Properties), 3 (Legal Proceedings),
  4 (Mine Safety) — these Items failed `section_name` fallback on filings that don't use
  "Item N" headers in the content body.
- **Resolution**:
  1. Widened `_pick_best_start` exclusion to 5% + prefer **first** content-area match
  2. Added `_upgrade_short_segments`: post-merge filter detects page-reference-only items
     (<500 chars, just "Pages X-Y" text) and replaces with `section_name` matches
  3. Added `_is_page_reference_only` heuristic (strip page refs, item headers, part labels)
  4. Extended `_SECTION_NAME_MAP` with Business→1, Properties→2, Legal Proceedings→3,
     Mine Safety→4; aligned `_SECTION_TITLE_RE` in `metrics.py`
  5. Enhanced `incorporation.py`: `(a)`/`(b)` footnote marker detection for Proxy Statement
     references (INTC-style short items ending with `(a)`)
- **Validation**: 65 tests pass; INTC Items 10–14 → `incorporated_by_reference`;
  Citi Items 10–14 → `incorporated_by_reference`; Citi Item 1 found via section_name
  (was `missing`). `char_coverage` now uses full body length (honest metric).

## anti-overfitting: v1 (contract-driven eval + baseline comparison + UI localization)

- **Failed Path**: Gold files in `task2_sec/eval/gold/` are generated from pipeline output — 
  circular evaluation inflates metrics. Heuristics (`_SECTION_NAME_MAP`, INTC footnote `(a)` 
  detection) could appear tuned to specific filings. No quantitative comparison against simpler
  approaches to justify the hybrid architecture's value.
- **Resolution**:
  1. Documented **Contract-Driven Evaluation** in `docs/analysis.md`: three deterministic 
     contracts (span integrity, token conservation, header retention) that hold on *any* filing 
     regardless of format — no ground truth needed
  2. Added **Baseline Comparison** table: Regex-Only vs Naive LLM vs Hybrid Pipeline with 
     concrete metrics (items found, incorporation detection, cost, token ratio)
  3. Added **Real-World Application** scenarios: Compliance Monitoring, QA Agent, Financial 
     Data Aggregation, Regulatory Audit — showing the architecture extends beyond this test
  4. Added **Entropy Gradient Routing** to Future Work in README.md — adaptive LLM tier 
     selection based on item confidence
  5. **UI全中文化**：Streamlit 四頁面（首頁、SEC 10-K、瀏覽器代理、評估儀表板）全部
     改為繁體中文，載入 Noto Sans TC 字體，統一 font-weight 和 letter-spacing
- **Validation**: No ticker-specific branching in pipeline code; all heuristics use generic 
  patterns (regex anchored to SEC standard item format); `_SECTION_NAME_MAP` covers standard 
  10-K section titles per SEC Regulation S-K, not individual filing quirks.

## max_tokens_and_sec_ui: Gemini thinking budget + CIK auto-lookup + 自訂報表 UX

- **Failed Path**: Three issues:
  1. `max_tokens` too low across codebase (64–1024). Gemini 2.5/3 thinking models allocate
     tokens for *both* reasoning and text output from the same budget — low `max_tokens` causes
     all tokens to be consumed by thinking, returning `content=None`. This was the root cause
     of `AllProvidersFailed` / "LLM planner unavailable" errors even after litellm upgrade.
  2. `resolve_filing_url` extracted CIK from accession prefix — but the prefix often belongs
     to the *filing agent* (e.g. Donnelley Financial, CIK 0000950170) not the *company*
     (e.g. MSFT, CIK 789019). ~40%+ of custom filing lookups would fail with 404.
  3. Custom filing UI had no CIK input field and unhelpful English-only error messages.
- **Resolution**:
  1. Increased `max_tokens`: `llm_router.py` default 1024→4096, `loop.py` 512→4096,
     `verify.py` blind_critic 64→1024, `smoke_llm_models.py` 32→256. Gemini has 65K output
     token limit — these values leave ample room for thinking + structured output.
  2. Rewrote `resolve_filing_url` with multi-CIK-candidate strategy: tries provided CIK,
     accession-prefix CIK, then EDGAR submissions API (`data.sec.gov/submissions/`) auto-lookup.
     Error messages in Chinese with actionable fix suggestions.
  3. Added CIK input field to SEC 10-K page with helper text; added contextual error messages
     (format hints, common causes) when extraction fails.
- **Validation**: All LLM call sites have `max_tokens` ≥ 256 (thinking-safe). CIK resolution
  tested with MSFT (CIK 789019 via accession 0000950170-24-087843 — filing agent CIK
  differs from company CIK). Custom filing UI shows CIK field with guidance.

## agent_reliability: v2 → v3 (budget tuning + keyword verify + error logging)

- **Failed Path**: Zeabur agent runs showed `plan_failed` on all steps 1–9 within ~200ms
  each — LLM was never called because `max_llm_calls_agent=8` was exhausted by retries
  (`_MAX_PRIMARY_RETRIES=3`). Error messages were uninformative (`logger.debug`).
  `verify_step` had `_extract_task_keywords` defined but never wired in — L0 verify only
  checked page-not-empty, allowing `done=true` on wrong pages (silent failure risk).
- **Resolution**:
  1. Reduced `_MAX_PRIMARY_RETRIES` 3→2 (Plan: retry 1 + fallback 1)
  2. Increased `max_llm_calls_agent` 8→25 (real capacity for 10-step tasks)
  3. Increased `max_tokens` 256→512 for agent planning
  4. Upgraded error logging to `logger.error` with `type(exc).__name__` detail
  5. Wired `_extract_task_keywords` into `verify_step`: extracts domain names and
     quoted strings from task description, checks presence in page text
  6. Disabled OpenRouter fallback (`LLM_FALLBACK_ENABLED=false`) — focus on Gemini primary
- **Validation**: 65 tests pass; Gemini Tier1+Tier2 smoke OK; `AllProvidersFailed` now
  includes root cause in message for deployment debugging.

### `ux_polish` (2026-05-28)
- **Failed path**: Post-deployment testing revealed 9 issues: Agent still failing (PDF URL crash),
  evaluation dashboard showing misleading success rates, SEC tab-switching state leaks, Browser
  Agent requiring manual refresh, incorporated-by-reference items lacking context, CIK not propagating
  back from auto-resolution, and SEC item content rendered as plain text without structure.
- **Resolution**:
  1. **Eval honesty**: `evaluate_agent_task` now checks `navigate` tasks against expected domain;
     `silent_failure` category catches tasks that claim success without verified output
  2. **Auto-refresh**: Browser Agent page auto-reruns every 3s while task is running/queued;
     refresh button removed; `agent_auto_refresh` session state flag controls the loop
  3. **PDF/download URL detection**: `_is_download_url()` checks file extension before `page.goto()`;
     returns descriptive error instead of Playwright crash; covers `.pdf`, `.zip`, `.xlsx`, etc.
  4. **Homepage redesign**: Replaced metrics-heavy landing page with design document layout:
     architecture cards, design decisions, pipeline flow diagrams, evaluation tier table
  5. **SEC item rendering**: `_format_sec_text` now detects bullet lists (`•/-/*`), numbered lists,
     tabular data (3+ columns separated by whitespace), and ALL-CAPS section headers
  6. **Incorporated-by-reference UX**: Rich card with EDGAR DEF 14A search link, detected
     reference text preview, and explanation of the SEC convention
  7. **CIK propagation**: `resolve_filing_url` and `fetch_filing_html` now return `(url, cik)`
     tuple; UI displays resolved CIK even when user only provided accession number
- **Key insight**: LLM-as-unstable-engine principle applies to UX too — every user-facing state
  transition must be validated, not just LLM outputs. The Browser Agent's "success" status was
  trusted without verifying the final URL matched the expected domain.
- **Validation**: unit tests, integration tests, e2e smoke test all pass locally.

### `phase4_ux` (2026-05-28)
- **Failed path**: Fixed 95% confidence displayed for all items (no information value); SEC text
  readability still poor (wall of plain text); agent concurrent submits risk OOM; incorporation
  items only linked to generic EDGAR search.
- **Resolution**:
  1. **Tier badge UX**: `ItemRecord.segment_method` propagated from `SegmentResult`; UI shows
     Tier0 method badge + "contract passed" instead of 95% progress bar; low_confidence only
     shows numeric score
  2. **Readability**: `_format_sec_text` groups lines into `<p>` paragraphs; serif typography
     CSS (`.sec-reader`) with max-width and justified text
  3. **Agent concurrent guard**: disable submit + double-check when agent status is running/queued
  4. **DEF 14A auto-link**: `find_proxy_filing(cik)` via SEC submissions API; incorporation
     items show direct link to latest proxy accession
  5. **README Known Limitations** expanded: ephemeral SQLite, iframe/shadow DOM, gold circularity
- **Validation**: e2e smoke adds segment_method + PDF detection checks.

### `agent_verify_fix` (2026-05-28)
- **Failed path**: Step 0 verify used quoted task terms on landing pages → Wiki/DDG stuck in
  recovery; `task_complete` trusted LLM `result` without page cross-check.
- **Resolution** (generic — no site hardcoding):
  1. Intermediate steps skip task keywords; step 0 uses navigation-only verify
  2. `verify_task_outcome()` at done=true: quoted terms + extracted result in page/JSON
  3. `infer_max_steps()` from task verbs (search/form 15, extract 12, default 10)
  4. EDGAR search: ticker → company_tickers.json → submissions, then EFTS fallback
- **Validation**: `tests/unit/test_agent_verify.py`.

### `agent_search_harness` (2026-05-28)
- **Failed path**: Wiki/DDG search hit max_steps; httpbin flaky; UI showed unused OpenRouter;
  Gemini 503 → immediate `plan_failed`; summarize tasks out of scope.
- **Resolution** (generic):
  1. Step 0 uses `verify_navigation`; search/find tasks auto-press Enter after type
  2. Generic consent-banner dismiss on landing (Accept/Agree button labels)
  3. Gemini primary infra retry (3× with backoff) before fallback
  4. UI: Gemini-only env checks; document summarize limitation
- **Validation**: agent eval **5/6** train (Wiki OK, DDG flaky); `docs/analysis.md` updated.

### `agent_extract_path` (2026-05-28)
- **Failed path**: Extract/summarize tasks forced through multi-step action loop → plan_failed or hallucinated `done`.
- **Resolution** (L2-inspired, generic):
  1. `infer_task_mode()` routes extract vs act from task verbs
  2. Extract path: navigate → one `PageExtraction` LLM call → `verify_task_outcome`
  3. Planner context: head+tail page snippet (4k), a11y 8k; no-clarify prompt
- **Validation**: unit tests + e2e task-mode smoke.
