# Whaleforce AI 編程測試

一個單一程式碼庫（monorepo），同時實作兩個任務，並共用一套「測試護欄」基礎設施：

- **任務一　瀏覽器自動化代理（Browser Agent）** — 用 LLM 規劃 + Playwright 執行，自動操作網頁（導覽、點擊、輸入、搜尋、抽取資訊）。
- **任務二　SEC 10-K 財報抽取（SEC 10-K Extraction）** — 從美國證交會（SEC）的 10-K 年報 HTML 中，把法定的 Item 1～16 各章節切分、驗證並結構化輸出。
- **共用層　`shared_harness/`** — LLM 路由、成本/預算熔斷、SQLite 任務紀錄、EDGAR 用戶端、Pydantic 資料契約、評估引擎等。

> **迭代過程**：主讀 [prompts/ITERATION.md](prompts/ITERATION.md)（失敗→修正→驗證）；[PLAN.md](PLAN.md) 為初期計畫與架構不變式摘要。

---

## 目錄

- [核心理念：把模型當成不穩定的引擎](#核心理念把模型當成不穩定的引擎)
- [快速開始](#快速開始)
- [線上 Demo 與部署](#線上-demo-與部署)
- [評審快速導覽](#評審快速導覽reviewer-quick-start)
- [專案結構](#專案結構)
- [任務一：瀏覽器代理](#任務一瀏覽器代理)
- [任務二：SEC 10-K 抽取](#任務二sec-10-k-抽取)
- [LLM 模型級聯](#llm-模型級聯litellm)
- [評估系統](#評估系統)
- [Eval Set 選樣理由與侷限](#eval-set-選樣理由與侷限)
- [路線圖 P0–P3（已落地）](#路線圖-p0p3已落地)
- [分析報告：效能、成本、擴充性與正確性驗證](#分析報告效能成本擴充性與正確性驗證)
- [測試](#測試)
- [設定與環境變數](#設定與環境變數)
- [設計取捨](#設計取捨)
- [已知限制](#已知限制)
- [未來工作（Future Work）](#未來工作future-work)
- [AI 在本專案中的使用](#ai-在本專案中的使用)

---

## 核心理念：把模型當成不穩定的引擎

整個程式碼庫的設計遵循一個思路（與 OpenAI 的 *Harness engineering* 觀點一致）：

> **不要指望靠「寫一個更長更聰明的 prompt」就解決問題。** LLM 是一個會出錯、不穩定的推理引擎；真正可靠的工程，是在它外面包上一層層「可驗證的護欄（harness）」。

具體落地成三根支柱：

| 護欄原則 | 在本程式碼庫的體現 | 可驗證證據 |
|---|---|---|
| **上下文鷹架**（餵給模型對的、精簡的輸入） | `llm_router` 模型級聯、`edgar_client` 快取、`prompt_loader` 外部化 prompt、a11y 文字壓縮 | `tests/integration/test_pipeline_tier0_only.py` |
| **架構約束**（強制輸出符合契約） | Pydantic schema、span 完整性校驗、`llm_parse` 跨廠商 JSON 解析 | `test_span_integrity.py`、`test_llm_parse.py` |
| **熵管理**（控制成本與失控風險） | `cost_tracker` 預算熔斷器、`eval_runner` 評估、pytest L1/L2/L3 分層 | `test_cost_tracker.py`、`reports/eval_*.json` |

一句話總結：面對 iXBRL、動態 DOM 這種「髒」輸入，採用 **契約 → 解析 → 驗證（Contract → Parse → Validate）**，而不是「寫個 prompt 求它別出錯（prompt-and-pray）」。

---

## 快速開始

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows（macOS/Linux: source .venv/bin/activate）
pip install -r requirements.txt
copy .env.example .env            # 然後編輯 .env 填入你的 API key
pytest -m unit                    # 跑確定性單元測試（不連網、不呼叫 LLM）
streamlit run streamlit_app.py    # 啟動多頁 Web 介面
```

- 本地密鑰放在程式碼庫根目錄的 **`.env`**（已被 `.gitignore` 忽略，不會提交）。`shared_harness/env.py` 會自動載入它，供 Streamlit、pytest、指令稿共用。
- 系統既有的環境變數優先級高於 `.env`。
- 只想驗證 LLM 模型 ID 是否可用：`python scripts/smoke_llm_models.py`。

---

## 線上 Demo 與部署

部署在 Zeabur，單一 Docker 服務、Streamlit 多頁應用。

- **線上網址**：https://whaleforce-coding-test.zeabur.app
- **程式碼倉庫**：https://github.com/paul-yang-AI/whaleforce-coding-test

| 頁面 | 對應內容 | 入口 |
|---|---|---|
| 首頁 Home | 總覽與架構說明 | `/` |
| SEC 10-K 抽取 | 任務二（基準集 / 泛化驗證 / 自訂） | 側邊欄 → SEC 10-K |
| **Browser Agent** | 任務一 | 側邊欄 → Browser Agent（**基準 / 泛化驗證 / 自訂** 三分頁） |
| 評估儀表板 | Train KPI + Held-out 基線 + 即時紀錄 | 側邊欄 → Eval |

部署關鍵環境變數見下方 [設定與環境變數](#設定與環境變數)。

---

## 評審快速導覽（Reviewer Quick Start）

> UI 預設 **3 檔 train** 是 eval 紀律設計（非功能缺失）；manifest 共 **11 檔**（3 train + 8 held-out）。

| 步驟 | 去哪裡 | 看什麼 |
|------|--------|--------|
| 1 | **SEC 10K → 基準集（Train · 3）** | 選 MSFT → 抽取 → Item 樹 + quality badge + 結構化閱讀 |
| 2 | **SEC 10K → 泛化驗證（Held-out · 8）** | 選 JPM → 看 bank TOC 4/4 通過；或 AAPL 2010 看已知 pre-iXBRL gap |
| 3 | **SEC 10K → 自訂報表** | 貼任意 accession 做 unseen filing 驗證（需 `SEC_USER_AGENT`） |
| 4 | **Eval → 基準評估 Train** | 按「載入存檔結果」→ SEC 3/3 + Agent 5/5 KPI |
| 5 | **Eval → Held-out 基線** | `heldout_baseline.json` 表格：6/8 ok；AAPL/KSCP 為誠實 gap |

深入分析：[docs/analysis.md](docs/analysis.md) · 迭代紀錄：[prompts/ITERATION.md](prompts/ITERATION.md)

---

## 專案結構

```
whaleforce-coding-test/
├── streamlit_app.py        # 入口：載入 .env、註冊 4 個頁面、側邊欄環境檢查
├── pages/                  # Streamlit 頁面
│   ├── 0_Home.py           #   總覽 / 架構圖 / 技術棧
│   ├── 1_SEC_10K.py        #   任務二 UI：基準集 / 泛化驗證 / 自訂抽取
│   ├── 2_Browser_Agent.py  #   任務一 UI：任務輸入 + 即時步驟時間軸
│   └── 3_Eval.py           #   評估儀表板
├── task1_agent/            # 任務一：瀏覽器代理
│   ├── agent/
│   │   ├── loop.py         #   主狀態機（規劃→執行→觀察→驗證→反思）
│   │   ├── browser.py      #   PlaywrightExecutor（實際操作瀏覽器）
│   │   ├── intent.py       #   意圖辨識（搜尋任務、補全缺漏參數）
│   │   ├── recovery.py     #   失敗分類 + 恢復策略表
│   │   ├── verify.py       #   L0 啟發式驗證 + 可選 Blind Critic
│   │   ├── extract.py      #   從頁面抽取任務結果
│   │   └── dom_serialize.py#   a11y 樹壓縮到字元預算內
│   └── eval/tasks.yaml     #   8 個代理評估任務（5 train + 3 heldout）
├── task2_sec/              # 任務二：SEC 10-K 抽取
│   ├── pipeline/
│   │   ├── fetch.py        #   抓取（封裝 edgar_client）
│   │   ├── normalize.py    #   正規化：剝離 iXBRL/指令稿/隱藏元素 → 純文字 body
│   │   ├── segment.py      #   分段：TOC / 正則 / 章節名 三層 + LLM 兜底
│   │   ├── validate.py     #   驗證：指標 + 合併引用偵測 + 仲裁 + 補齊缺漏項
│   │   ├── incorporation.py#   偵測「以引用併入（incorporated by reference）」
│   │   ├── metrics.py      #   span 完整性 / token ratio / 標題保留
│   │   ├── arbiter.py      #   Tier2 邊界仲裁（僅調整偏移，不改寫原文）
│   │   ├── html_snippet.py #   每段原始 HTML 片段（目前未接入 UI，見 Future Work）
│   │   └── run.py          #   端到端串接
│   └── eval/
│       ├── manifest.json   #   11 份 filing（3 train + 8 held-out）
│       ├── gold/           #   train 的 gold 邊界標註
│       └── cache/          #   離線 CI 用的 EDGAR HTML 快取
├── shared_harness/         # 跨任務共用基礎設施（見下表）
├── prompts/                # 版本化 prompt（v1_*.txt）+ SOP（sops/*.md）+ 迭代紀錄；索引見 prompts/README.md
├── tests/                  # unit / integration / eval 三層測試
├── scripts/                # 評估、基線、煙霧測試等 CLI
├── reports/                # 評估產物（JSON 已提交；CSV 執行時產生）
├── docs/analysis.md        # 深入分析與權衡說明
├── Dockerfile              # Playwright 基礎映像 + Streamlit
└── requirements*.txt       # 相依套件
```

### `shared_harness/` 模組一覽

| 模組 | 作用 |
|---|---|
| `llm_router.py` | litellm 封裝：Tier1/2 主用 + primary 重試後單次 fallback、預算檢查、成本紀錄、schema 解析 |
| `llm_config.py` | Tier → 模型 ID 對應（可用環境變數覆寫） |
| `llm_parse.py` | 跨廠商 JSON 正規化（剝掉 ```` ```json ```` 圍欄後解析成 Pydantic） |
| `cost_tracker.py` | 執行緒安全成本統計 + 熔斷器；`llm_budget_guard()` 序列化 check/record |
| `job_store.py` | SQLite（預設 WAL，可 `SQLITE_JOURNAL_MODE=TRUNCATE`）：runs / steps / cost events |
| `edgar_client.py` | SEC 唯一 HTTP 入口：抓取、搜尋、CIK 解析、限速、HTML 快取 |
| `prompt_loader.py` | 載入 `prompts/sops/{name}.md` 或 `prompts/v1_{name}.txt` |
| `eval_runner.py` | 跑 SEC manifest + 代理任務，評分，匯出 CSV，彙總 KPI |
| `env.py` | 載入根目錄 `.env`（不覆寫已存在的環境變數） |
| `schemas/sec_schema.py` | `ItemStatus`、`ItemRecord`、`FilingExtraction`、`STANDARD_ITEMS`（Item 1–16） |
| `schemas/common.py` | `AgentAction`、`BoundaryDecision`、`CriticVerdict`、`PageExtraction` |
| `sec_ui.py` / `eval_ui.py` | 純函式 UI 輔助（結果上下文比對、KPI HTML），便於單元測試 |

---

## 任務一：瀏覽器代理

### 它在做什麼

給定一個自然語言任務（例如「打開 Hacker News，告訴我第一條新聞的標題」）和起始 URL，代理會自己一步步操作瀏覽器，直到完成並給出結果。

### 狀態機（State Machine）

```
導覽(Navigate) → LLM 規劃(Plan) → 執行(Act) → 觀察(Observe) → 驗證(Verify) → 反思(Reflect, 僅失敗時)
```

實際執行流程（`task1_agent/agent/loop.py`）：

1. **第 0 步**：導覽到起始 URL。
2. **抽取捷徑**：若辨識為「抽取類」任務且導覽成功，直接做一次 LLM 抽取並驗證 → 完成。
3. **第 1 步及之後**：由 Tier1 LLM 規劃下一個動作（prompt = `agent_plan`，輸出受 `AgentAction` schema 約束），再交給執行器執行。
4. **完成判定**：規劃器輸出 `done=true` → 做終局驗證 → `task_complete` 或被拒絕 `task_complete_rejected`。
5. **恢復（Recovery）**：導覽失敗時按失敗類型走「策略表」（每步最多 2 策略）；**動作步失敗**亦會先試 1 次 deterministic recovery 再 replan。
6. **卡死偵測**：連續 3 次 `type` 但 URL 沒變 → 判定失敗。
7. **可選終局把關**：`ENABLE_BLIND_CRITIC=true` 時，額外用一個「盲審」LLM 獨立判斷結果是否可信。

### 支援的動作類型（LLM 可規劃）

`click`（點擊）、`type`（輸入，搜尋任務會自動按 Enter 送出）、`scroll`（捲動）、`press_key`（按鍵）、`navigate`（導覽）、`none`（無操作/結束）。

執行器（`browser.py`）基於同步 Playwright + 無頭 Chromium；`reset_context()` 在 eval 每 task 間隔離 cookie/storage；會在導覽前拒絕 PDF / 下載型 URL，並嘗試關閉常見的 cookie 同意橫幅。

### 恢復策略：按「失敗類型」對症下藥

`recovery.py` 用 `FailureType` 列舉把失敗歸類，再查 `STRATEGY_TABLE` 取對應策略（如捲動、返回上一頁、延長等待），而不是一律重試。這是「確定性 SOP」的體現——邏輯寫死在程式碼裡，由 L1 測試守護。

### 自我維護（Self-maintenance）— 不依賴寫死 selector

題目要求 UI / selector 變動時能**偵測並動態調整**。本專案用三層通用機制（非 per-site 腳本）：

| 機制 | 做法 | 對比寫死 selector |
|------|------|-------------------|
| **a11y 樹規劃** | 每步壓縮 accessibility tree 餵 LLM，用 visible label / role 規劃動作 | 不依賴 `#id`、`.class` 等易碎 CSS |
| **多策略定位** | `click` / `type` 依序嘗試 text → role → placeholder → label | 單一 selector 失效時仍有 fallback |
| **Recovery 策略表** | `ELEMENT_NOT_FOUND` → scroll → role_name → relax_selector → replan | blind retry 變成**有順序的 SOP** |
| **Search URL fallback** | type loop stuck → `/?q={query}` navigate（通用，非 site-specific） | DuckDuckGo/Bing 等支援 query param |
| **終局驗證** | `success_hints` + 失敗敘述偵測（blocked / could not / rate limit） | 避免 planner 宣告 `done=true` 但任務未達成 |

典型鏈路：`type` 找不到元素 → `FailureType.ELEMENT_NOT_FOUND` → scroll → `get_by_role("searchbox")` → 仍失敗則 replan。Form 任務額外：填完欄位後自動點 Submit / Enter（`_try_click_form_submit`），減少 type loop。

**已知 gap（held-out 誠實基線）：** DuckDuckGo consent/SERP、SEC rate-limit 時仍可能 fail — 見 `reports/agent_heldout_baseline.json`。

### 評估任務（`task1_agent/eval/tasks.yaml`）

共 **10** 個任務：5 個 train + **5** 個 heldout。Train：**5/5 成功，silent_failure=0**（per-filing regression contract）。  
Held-out 基線（`reports/agent_heldout_baseline.json`）：**3/5 ok**（forms、python docs、quotes ✅；SEC EDGAR、DDG 已知 gap — **無 silent failure**）。

| 站點 | 任務類型 | 狀態 | 說明 |
|---|---|---|---|
| example.com | navigate | ✅ Train | 標題驗證，2 步 |
| news.ycombinator.com | extract | ✅ Train | 抽取頭條標題 |
| github.com | navigate | ✅ Train | LLM 規劃導覽到 `/python/cpython` |
| httpbin.org | extract | ✅ Train | 抽取請求標頭 |
| wikipedia.org | search | ✅ Train | 多步搜尋；`success_hints` URL 驗證 |
| duckduckgo.com | search | ⚠️ Held-out | headless flaky（consent/SERP）；`expect_url_contains: q=` |
| sec.gov | navigate | ⚠️ Held-out | EDGAR rate-limit / max_steps；`success_hints` + 失敗敘述偵測 |
| httpbin.org | form | ✅ Held-out | POST 表單；自動 Submit + `/post` 驗證 |
| docs.python.org | navigate | ✅ Held-out | **frozen** held-out（勿為此任務調 prompt） |
| quotes.toscrape.com | extract | ✅ Held-out | 靜態 HTML 抽取；domain diversity |

---

## 任務二：SEC 10-K 抽取

### 它在做什麼

10-K 是美國上市公司的年度報告，法定結構為 Part I–IV 下的 Item 1～16（如 Item 1 業務、Item 1A 風險因素、Item 7 MD&A、Item 8 財務報表等）。本管線從原始 HTML 中把每個 Item 精確切分出來，並保證 **零幻覺**：輸出文字必須是原文的子字串。

### 前端呈現（SEC 10-K 頁）

| 分頁 | 內容 | 用途 |
|------|------|------|
| **基準集（Train · 3）** | MSFT / INTC / Citi | 開發 KPI；抽取後顯示 **Required KPI** 主指標 |
| **泛化驗證（Held-out · 8）** | BRK.B、JPM、AAPL 2010… | 不在 train 內；每筆顯示基線預期 badge |
| **自訂報表** | EDGAR 搜尋或 accession | 評審 unseen filing 現場驗證 |

Held-out 分頁的 badge 來自 `reports/heldout_baseline.json`；**AAPL 2010 / KSCP 等失敗為已知邊界**，非 silent failure。

### 管線流程（`task2_sec/pipeline/run.py`）

```
抓取(Fetch) → 正規化(Normalize, 剝離 iXBRL) → 分段(Segment) → 驗證(Validate) → 輸出(FilingExtraction)
```

每個 Item 都會得到一個狀態：`extracted`（已抽取）/ `low_confidence`（低信心）/ `missing`（未找到）/ `incorporated_by_reference`（以引用併入）/ `not_applicable`（不適用）。

### 三層分段 + LLM 兜底（為「沒見過的 filing」設計）

為了泛化到任意公司，分段器採用逐層降級：

1. **TOC 錨點**（`toc`）：解析 HTML 裡 `<a href="#...">` 目錄連結，對應到 Item ID，再用正則在內文裡定位。
2. **行首正則**（`regex`）：`^\s*(?:ITEM|Item)\s+<id>`，只比對行首標題，避免誤抓內文裡「見 Item 1」這類內聯引用。
3. **章節名對應**（`section_name`）：當上面找到的段落太少或覆蓋率過低時，用 19 個標準 10-K 章節標題（Business、Risk Factors、Properties、Legal Proceedings、MD&A 等）兜底，適配沒有「Item N」標題的 filing。
4. **LLM 兜底**（`llm`）：僅當 Tier0 仍漏掉很多項（缺漏 > 5）或覆蓋率 < 30% 時，才分塊呼叫 Tier1，讓模型給出字元偏移；文字永遠取 `body[start:end]`，不讓模型「複述」。

### 驗證與指標（`metrics.py` / `validate.py`）

- **Span 完整性**：`body[start:end] == item.text`，從源頭杜絕幻覺。
- **Token 比率 ≥ 0.85**：保證是「原文」而非「摘要」。
- **標題保留**：段首應包含該 Item 的標題特徵。
- **邊界仲裁（Arbiter，Tier2）**：僅當某段「低信心」且開啟仲裁時，用 Tier2 模型在局部視窗內**只調整邊界偏移**（不改寫原文）。預設的 train 評估走 Tier0-only（`use_arbiter=False`），仲裁屬於進階/爭議場景。

### 合併引用與交叉引用索引

- **以引用併入（incorporated by reference）**：很多公司的 Item 10–14 會寫「內容見委託書（Proxy/DEF 14A）」。管線偵測到後**不會編造內文**，而是標記狀態並（在已知 CIK 時）自動連結到原文。
- **交叉引用索引（cross-reference index）**：像 INTC 這類 cross-reference 10-K 會在索引表列出 `Pages N`。Tier0 會以 **bidirectional section_name upgrade** 嘗試定位真實正文（1A / 7 / 8 等）；若該 Item 在整份 HTML 中**完全沒有章節錨點**（如 INTC Item 1 僅索引列），仍誠實標為 cross-ref，不編造內文。
- **銀行 TOC 索引列（裸頁碼）**：像 Citi 這類 filing 在開頭有一大段「Item 標題 + 裸頁碼範圍（如 70–129, 174–178）」的目錄列，內文卻只用章節標題（如 `MARKET RISK`、`DISCLOSURE CONTROLS AND PROCEDURES`）而不再寫 `Item 7A` / `Item 9A`。管線會：(1) 辨識裸頁碼索引列與 **front mega-TOC**（`5.` / `6.` 編號列）；(2) 動態偵測 TOC 區塊（scrub 用）並以較窄的 **content_start** 保留 Item 15 等真實章節；(3) 捨棄 front index stub、補上 sibling items（如 9A/9B）；(4) 保留 Part III 索引列上的 **incorporated by reference** 偵測（`*` / `**` footnote）。
- **Not applicable**：短段且僅含 `Not Applicable` / `[Reserved]`（無頁碼索引）→ `not_applicable` 狀態。

### 範例 filing

| 公司 | Accession | 特點 / 表現 |
|---|---|---|
| **MSFT** | `0000950170-24-087843` | 6.8 MB iXBRL、標準 TOC，22 個 Item 全數抽取，$0.00 |
| **INTC** | `0000050863-25-000009` | 重度 iXBRL + cross-ref；**required 1A/7/8**；Item 1 EOF cross-ref 不算 required |
| **Citi (C)** | `0000831001-25-000067` | 大型銀行 front mega-TOC + incorporated；**1A/7/7A/8/9A/9B** 真實正文；front 索引 stub 誠實 `missing`；Item 10–14 incorporated |
| **BRK.B** | `0000950170-25-025210` | Heldout，K-1 式 TOC 變體；本地快照 4/4 必需項、21 項抽取 |

**反過度擬合措施**：管線程式碼裡**沒有任何按 ticker / accession 的特判分支**；覆蓋率以「完整正規化 body」為分母計算；gold 邊界由管線輸出再生成（這點是循環的，已在 `docs/analysis.md` 中如實說明）。

---

## LLM 模型級聯（litellm）

| Tier | 主用（Primary） | 兜底（Fallback） | 用途 |
|---|---|---|---|
| 1 | `gemini/gemini-3-flash-preview` | `openrouter/deepseek/deepseek-v4-pro` | 代理規劃、恢復、抽取、Blind Critic、SEC LLM 兜底分段 |
| 2 | `gemini/gemini-3.1-pro-preview` | `openrouter/qwen/qwen3.5-397b-a17b` | SEC 邊界仲裁 |

- Fallback 在遇到 429/5xx/校驗失敗時，對每個 `(tier, call_site)` **只觸發一次**。
- 若未設定 `OPENROUTER_API_KEY`，自動跳過 fallback（純 Gemini）。
- 觸發預算熔斷（`BudgetExceeded`）時，直接拒絕呼叫、零 API 花費。
- 所有模型 ID 都可用環境變數覆寫（見 `.env.example`）。

---

## 評估系統

`shared_harness/eval_runner.py` 統一驅動兩個任務的評估：

- **SEC**：讀 `task2_sec/eval/manifest.json` → 按 split 過濾 → 抓取 + 抽取 → 對照 gold 邊界與契約指標評分。
  - **Required KPI（主指標）**：預設 `["1","1A","7","8"]`；**cross-reference / bank mega-TOC** 格式（INTC、Citi）覆寫為 `["1A","7","8"]`（Item 1 無 in-body 正文錨點）。
  - **Quality 分層**：`required_prose_count`（真實長正文）、`required_cross_ref_count`（Pages N 索引列，算 found 但非 prose）、`expected_missing_ok_count`（manifest 標記的合法 missing，如 Citi Item 1/6/16）。
  - **Gold 邊界**：`gold_items = ["1","1A","1B","1C","7","8","10","14"]`（第二層契約，與 required 分開）。
- **Agent**：讀 `task1_agent/eval/tasks.yaml` → 真正啟動 Playwright 跑任務 → 紀錄成功率、步數、延遲、成本。
- **產物**（`reports/`）：
  - `eval_train.csv`：SEC + 代理統一指標（評估頁展示，git 追蹤）。
  - `eval_summary.json`：P50/P95、成本、成功率等彙總 KPI。
  - `heldout_snapshot.json`：BRK.B heldout 快照（**不用於調參**）。
  - `baseline_comparison.json`：regex-only vs 樸素 LLM vs 混合方案的對比。

評估頁（Eval）支援「📂 載入存檔結果」（瞬間顯示已提交基準）與「重跑 train 基準」；**Held-out SEC 基線**在「🔬 Held-out 基線」分頁唯讀展示 `heldout_baseline.json`。

---

## Eval Set 選樣理由與侷限

### Train（3 檔）— 結構變異最小充分集

Train 集**刻意不堆 ticker 數量**，而是用三檔走過三條不同程式路徑（Tier0、$0/filing KPI）：

| Filing | 代表的變異維度 | 走到的程式路徑 |
|---|---|---|
| **MSFT** | 標準 iXBRL、規矩 Item 標題 | TOC + regex（happy path） |
| **INTC** | Cross-reference + topic-index rows | section_name bidirectional upgrade |
| **Citi** | 金融 mega-TOC、裸頁碼索引、incorporated | section_name + TOC stub 清除 |

### Held-out（11 檔 manifest，依快取條件執行）

| Filing | 變異軸 | 備註 |
|---|---|---|
| **BRK.B** | K-1 式 TOC | 永遠執行（有預設快取） |
| **MSFT FY2020** | 縱向格式漂移 | `cache_optional` |
| **O (REIT)** | 不動產 REIT 結構 | `cache_optional` |
| **AAPL 2010** | pre-iXBRL HTML | `cache_optional` |
| **JPM** | 第二大型銀行 TOC | held-out **4/4**；header quality pick 泛化 Citi heuristics |
| **NEM** | 礦業 / Item 4 Mine Safety | `cache_optional` |
| **GROW** | 精簡型小型 issuer | `cache_optional` |
| **KSCP 10-K/A** | Part III 修正件 | 合法 missing 語意 |

```bash
python scripts/cache_heldout_filings.py      # 下載 held-out HTML 至 eval/cache/
python scripts/run_heldout_baseline.py      # Tier0 baseline → reports/heldout_baseline.json
python scripts/run_heldout_baseline.py --with-llm  # 可選：LLM 增量路徑對照
```

手動 spot-check 紀錄見 **[docs/eval_spot_checks.md](docs/eval_spot_checks.md)**。

### 目前抽取得好的 filings（範例）

| 公司 | Accession | 說明 |
|---|---|---|
| **MSFT** | `0000950170-24-087843` | 標準 iXBRL；Items 1/1A/7/8 完整原文 |
| **INTC** | `0000050863-25-000009` | 交叉引用索引；**1A / 7 / 8 已升級為真實正文**（section_name）；Item 1 若仍 cross-ref 屬該格式無正文錨點 |
| **Citi** | `0000831001-25-000067` | Item 7/7A/8 真實內文；Item 10/14 incorporated |
| **BRK.B**（held-out） | `0000950170-25-025210` | K-1 式 TOC；section_name 兜底 |

### 仍有困難 / 尚未支援（誠實邊界）

| 類型 | 例子 | 現況 |
|---|---|---|
| **pre-iXBRL 舊 HTML** | AAPL 2010 | held-out **2/4** required；`missing_item_header` |
| **第二大型銀行 TOC** | JPM | held-out **4/4**；`_header_start_quality_key` + 標題可選句點 |
| **10-K/A 修正件** | KSCP | 僅 Part III 補件；**0/4** required（預期行為） |
| **PDF-only 舊 filing** | 2000 年代部分 OTC | 不支援（管線只處理 HTML） |
| **20-F 等非 10-K** | 外商 issuer | 未測試、未支援 |
| **7A 嵌在 Item 7 內** | 部分 issuer 無獨立 7A 標題 | 可能 `missing` 或邊界不完整 |
| **Item 內表格結構** | 任何大型 iXBRL | normalize 壓平表格；展示層重排版 |

**方法論限制**：train gold 由 Tier0 管線輸出再生成（循環）；`required_items` 已加 **content-quality**（TOC stub 不算通過）。契約指標（span / token / header）+ spot-check 補足。

**效能**：Citi 等 mega-HTML filing（~17MB）已優化 TOC 解析（僅掃描文件前段 + 索引 id lookup），單份抽取約 **4–6 秒**（本地 Tier0）。

---

## 路線圖 P0–P3（已落地）

依「LLM 手術刀式接入 × 泛化 / 防 overfit」討論，下列項目已實作並有測試覆蓋：

### P0 — 評估誠實度

| 項目 | 實作 |
|---|---|
| **Content-quality 指標** | `task2_sec/pipeline/content_quality.py`：`is_likely_toc_stub()`、`assess_required_item()` |
| **Eval 整合** | `eval_runner.py`：`toc_stub_count`、`required_quality_failures`、失敗類別 `toc_stub_required_item`；必需項嚴格檢查（TOC stub 不算 found） |
| **擴充 manifest** | 11 檔 held-out（BRK + 7 optional 變異軸）；`cache_heldout_filings.py` |
| **Gold 出處** | `manifest.json` → `gold_provenance`；`scripts/regenerate_gold.py` 固定 `use_llm_fallback=False` 並寫入 `provenance` |
| **「抽好」定義** | 正確狀態 + 零幻覺原文；`missing` / `cross-ref` / `incorporated` 亦為合法結果（見 analysis） |

### P1 — Tier0 穩健化

| 項目 | 實作 |
|---|---|
| **自適應常數** | `segment.py`：`_scale_short_segment_chars`、`_scale_toc_cluster_gap`、`_scale_short_ratio_threshold`、`_content_start_for_names` 依 `body_len` 縮放 |
| **替代標題安全** | Item 7A/8 多命中時，優先非 TOC 區、非 page-ref 窗口的唯一錨點 |
| **Gold 再生文件** | 見下方 CLI：`python scripts/regenerate_gold.py` |

### P2 — LLM 手術刀（分類 / 邊界，非全文合成）

| 項目 | 實作 |
|---|---|
| **Tier1 結構分類** | `segment_classify.py`：`real_content` / `toc_index` / `cross_ref_only` / `incorporated`；可選 `ENABLE_SEC_LLM_CLASSIFY` |
| **Tier2 仲裁** | UI 已傳 `run_id` → `low_confidence` 時可觸發 arbiter |
| **Entropy 路由** | Tier0 通過 → $0；短段 + TOC stub 密度 → section_name；missing/coverage → LLM fallback |
| **遞迴 LLM 拆分** | `_segment_from_llm` chunk 失敗時對半重試（`max_split_depth=2`） |
| **Eval 雙模式** | `python scripts/run_eval.py --tier0-only`（預設 KPI）／`--with-llm`／`--with-arbiter` |

### P3 — 產品與長期

| 項目 | 實作 |
|---|---|
| **UI 品質徽章** | TOC 索引 / 交叉引用 / 合併引用 / 缺失 / 低信心 / 真實內文 |
| **縱向 held-out** | MSFT FY2020 manifest 條目（`cache_optional`） |
| **char→HTML 映射** | 仍列 Future Work #1（analysis 有說明） |

---

## 分析報告：效能、成本、擴充性與正確性驗證

> 以下為摘要數字；完整分析（baseline 對比、失敗模式分析 FMA、可觀測性、held-out 快照、應用場景）見 **[docs/analysis.md](docs/analysis.md)**。數字取自 `reports/eval_summary.json` 與 `reports/eval_train.csv`。

### 效能與成本（實測）

| 指標 | 任務二 SEC 10-K | 任務一 瀏覽器代理 |
|---|---|---|
| 樣本 | 3 份 train filing | 5 個 train 任務 |
| 成功 / 召回 | 必需項 100%（per-filing required contract：MSFT 4/4、INTC/Citi 3/3） | 成功率 100%（5/5） |
| 靜默失敗（silent failure） | — | **0** |
| 每單位延遲 P50 / P95 | 單份秒級（本地，無 LLM） | **9.3s / 9.9s** |
| 每單位成本 P50 | **$0.00 / filing**（Tier0 全覆蓋，零 LLM） | **$0.0077 / task** |
| LLM 呼叫總數 | 0（eval 路徑） | 8 |
| Token 比率 P50 | 0.98–0.99（保證原文、非摘要） | — |

**成本紀律**：全域預算 $20、每代理執行 $0.50、每份財報 $0.30，外加單次呼叫次數上限；超限即觸發 `BudgetExceeded` 並零 API 花費（見 `scripts/demo_circuit_breaker.py`）。SEC 主路徑靠 Tier0（正則 + BS4）達到 **$0.00**，LLM 只在低信心邊界仲裁或大量缺漏時才啟用。

### 正確性驗證（沒有公開 ground truth 時，如何證明自己是對的）

不依賴人工標註，而是用三個**確定性契約**——對任何 filing 都成立，與 ticker / 格式無關：

| 契約 | 檢查什麼 | 過擬合風險 |
|---|---|---|
| **Span 完整性** | `body[start:end] == text`（存檔前強制） | 無（純子字串） |
| **Token 守恆** | `token_ratio ≥ 0.85`，證明是原文非摘要 | 無（比率指標） |
| **標題保留** | 段首 200 字內含章節標題 | 低（通用樣式） |

此外有 **baseline 對比**（regex-only vs 樸素 LLM vs 本混合管線：必需項召回 66.7% / 50% / **100%（per-filing required contract）**，成本 $0 / $3.17 / **$0**）佐證設計取捨；代理端則以 **L0 每步驗證 + 可選 Blind Critic** 防止「成功卻沒結果」的靜默失敗。`task2_sec/eval/gold/` 的 gold 檔承認是循環產生（由管線輸出再生成），故契約才是真正的品質保證。

### 擴充性（Scalability）

- **更多文件類型**：三層分段 + 章節名對應可推廣到 10-Q / 8-K / 20-F；新增 filing 只需擴充 manifest 與章節標題表，管線無 ticker 特判。
- **吞吐與限速**：`edgar_client` 統一限速 + HTML 快取，可安全批次抓取；`job_store`（SQLite WAL）記錄每次 run / step / 成本事件，便於稽核與離線重跑。
- **成本隨難度自適應**：易解項留在 Tier0（$0），難解項才升級 Tier1/Tier2，避免「一律呼叫大模型」的成本爆炸（延伸方向見 Future Work 的熵梯度路由）。
- **部署**：單一 Docker / Streamlit 多頁，水平複製即可擴充；目前單容器限制單次並行代理執行（記憶體考量，見已知限制）。

---

## 測試

分三層（marker 見 `pytest.ini`），約 **173** 個測試函式（unit 160 + integration 13；eval 另計）：

```bash
pytest -m unit          # L1：確定性，零 LLM、零網路
pytest -m integration   # L2：mock 整合
pytest -m eval          # L3：SEC manifest + 代理任務（較慢，用快取）
```

CLI 評估指令稿：

```bash
python scripts/run_eval.py --split train --tier0-only   # 預設 Tier0 KPI（無 LLM）
python scripts/run_eval.py --split heldout --tier0-only # BRK.B + 已快取之 optional 檔
python scripts/run_eval.py --split train --with-llm --with-arbiter  # LLM 增量路徑
python scripts/regenerate_gold.py                     # 重生成 train gold（Tier0 only）
python scripts/run_agent_eval.py                        # SEC + 代理實跑 → CSV + summary
python scripts/run_heldout_snapshot.py                  # 精簡 held-out 快照
python scripts/demo_circuit_breaker.py                  # 預算熔斷示範
```

代表性測試：`test_span_integrity.py`、`test_regex_boundary_fallback.py`、`test_metrics_conservation.py`（SEC）；`test_recovery_routing.py`、`test_agent_verify.py`、`test_agent_intent.py`（代理）；`test_cost_tracker.py`、`test_llm_parse.py`（護欄）。

---

## 設定與環境變數

| 變數 | 必填 | 說明 |
|---|---|---|
| `GEMINI_API_KEY` | 是 | Tier1/Tier2 主用模型 |
| `SEC_USER_AGENT` | 是 | SEC 要求的 UA，格式：`"公司名 聯絡人 email@domain.com"` |
| `RUN_BUDGET_USD` | 否 | 全域預算，預設 `20` |
| `ENABLE_BLIND_CRITIC` | 否 | 預設 `false`；設 `true` 啟用代理終局盲審（額外成本） |
| `ENABLE_SEC_LLM_CLASSIFY` | 否 | 設 `true` 時，Tier1 對 UNKNOWN 段做結構分類（enum，不生成正文） |
| `OPENROUTER_API_KEY` | 否 | 僅作程式碼層 fallback（UI 不展示） |
| `LLM_FALLBACK_ENABLED` | 否 | 程式碼預設 `true`；設 `false` 則純 Gemini |
| `LLM_TIER{1,2}_{PRIMARY,FALLBACK}` | 否 | 覆寫預設模型 ID |

部署：`Dockerfile` 基於 `mcr.microsoft.com/playwright/python`（自帶 Chromium 相依），安裝 `requirements-docker.txt`（含 Playwright / edgartools），啟動 `streamlit run streamlit_app.py`（埠 8501，附健康檢查）。

---

## 設計取捨

| 理想做法 | 本專案選擇 | 原因 |
|---|---|---|
| 即時 SSE 推流 | SQLite + 重新整理 | 可稽核、可重現 > 動畫效果 |
| 12+ 個代理任務 | 8 個有深度的任務 | 證明「恢復能力」，而非堆成功率 |
| 16 項完整 gold | 全項狀態 + 8 項 gold | 在沒有公開 ground truth 下更務實 |
| 兩套部署 | 單一 Docker、多頁 | 一個 URL 同時承載兩個任務 |

---

## 已知限制

**部署**
- Zeabur 容器檔案系統是暫時的：代理執行歷史與成本事件在重新部署後會重置；評估產物存於 git 追蹤的 `reports/*.csv` 與工作階段內的 SEC HTML 快取。
- Playwright 記憶體：UI 限制單次並行代理執行；小容器（~1 GB）上多任務並行可能 OOM。

**瀏覽器代理**
- 登入 / CAPTCHA：直接回報 `blocked`，不嘗試繞過。
- PDF / 下載 URL：導覽前即拒絕。
- iFrame / Shadow DOM：不支援，a11y 樹可能漏內容。
- 動態 SPA：DOM 可能在逾時內未穩定，靠 `extend_wait` 恢復。

**SEC 10-K**
- 信心分數：契約校驗通過時固定 0.95，UI 改以「抽取方式徽章（regex/TOC/section_name）」呈現。
- 正規化會壓平 HTML：表格結構在抽取階段遺失，靠展示層重新格式化提升可讀性。
- 交叉引用 / 合併引用內容不內聯（防幻覺），改為連結原文。
- 原始 HTML 片段檢視：啟發式錨定在 iXBRL / 交叉引用式 filing 上不可靠，**已從 UI 移除**（見 Future Work）。
- 樸素 LLM 基線：取自文獻估算，非實測 API 呼叫。

**不支援**
- PDF-only 的舊 filing（本管線只處理 HTML）。
- 完全沒有 TOC 或 Item 標題的 filing 可能產生 `missing`。
- 非英文 filing（如 20-F）未測試。

---

## 未來工作（Future Work）

1. **忠實 HTML / 表格檢視**：按 Item 渲染原始 HTML 與表格。目前啟發式錨定（靠標題文字在 HTML 裡搜尋）在 iXBRL / 交叉引用式 filing 上不可靠，已從 UI 移除；後續應改用「內文字元偏移 → HTML 偏移對應」來精確定位（`task2_sec/pipeline/html_snippet.py` 模組已保留）。
2. **DSPy**：用評估指標自動編譯恢復 / 邊界 prompt。
3. **VLM / Set-of-Mark**：截圖座標點擊，應對 Canvas / React 類站點。
4. **多智能體辯論（Multi-Agent Debate）**：抽取器 vs 合規稽核器，用於邊界仲裁。
5. **外部技能信任**：對第三方 SOP 做白名單 + schema 校驗。
6. **熵梯度路由（Entropy Gradient Routing）**：按信心度路由不同 LLM Tier——高信心項留在 Tier0（正則，$0），低信心項升級到 Tier1（Flash）或 Tier2（Pro），在保證品質的同時降低成本。

---

## AI 在本專案中的使用

| 階段 | 工具 | 產出 |
|---|---|---|
| 架構與不變式 | Cursor | [PLAN.md](PLAN.md)（摘要）、[prompts/README.md](prompts/README.md) |
| 10-K 分段 / 指標 | Cursor（TDD） | `test_bs4_anchor.py`、`test_regex_boundary_fallback.py` |
| 代理恢復設計 | Cursor + PLAN | `recovery.py` + `prompts/sops/recovery.md` |
| 評估設計 | Cursor | `manifest.json`、`tasks.yaml` |
| Eval 誠實度 / content-quality | Cursor | `content_quality.py`、[ITERATION.md#content_quality_toc_stub](prompts/ITERATION.md) |
| Held-out 擴充與 baseline | Cursor | `heldout_baseline.json`、[ITERATION.md#heldout_eval_expansion](prompts/ITERATION.md) |
| 除錯迭代 | Cursor | `prompts/ITERATION.md`（v1→v2，附測試證據） |

詳細的「失敗路徑 → 解決 → 驗證」敘事見 [prompts/ITERATION.md](prompts/ITERATION.md)；更深入的分析與權衡見 [docs/analysis.md](docs/analysis.md)。

---

## License

MIT（可按需調整）。
