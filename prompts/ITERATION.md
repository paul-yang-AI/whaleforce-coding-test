# Prompt Iteration Log

Record v1→v2 changes with Failed Path / Resolution / Validation.

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
