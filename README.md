# Whaleforce AI 編程測試

一個單一程式碼庫（monorepo），同時實作兩個任務，並共用一套「測試護欄」基礎設施：

- **任務一　瀏覽器自動化代理（Browser Agent）** — 用 LLM 規劃 + Playwright 執行，自動操作網頁（導覽、點擊、輸入、搜尋、抽取資訊）。
- **任務二　SEC 10-K 財報抽取（SEC 10-K Extraction）** — 從美國證交會（SEC）的 10-K 年報 HTML 中，把法定的 Item 1～16 各章節切分、驗證並結構化輸出。
- **共用層　`shared_harness/`** — LLM 路由、成本/預算熔斷、SQLite 任務紀錄、EDGAR 用戶端、Pydantic 資料契約、評估引擎等。

> 想看「我是怎麼一步步迭代過來的」，請讀 [PLAN.md](PLAN.md)（階段計畫）與 [prompts/ITERATION.md](prompts/ITERATION.md)（失敗→修正→驗證的過程紀錄）。

---

## 目錄

- [核心理念：把模型當成不穩定的引擎](#核心理念把模型當成不穩定的引擎)
- [快速開始](#快速開始)
- [線上 Demo 與部署](#線上-demo-與部署)
- [專案結構](#專案結構)
- [任務一：瀏覽器代理](#任務一瀏覽器代理)
- [任務二：SEC 10-K 抽取](#任務二sec-10-k-抽取)
- [LLM 模型級聯](#llm-模型級聯litellm)
- [評估系統](#評估系統)
- [Eval Set 選樣理由與侷限](#eval-set-選樣理由與侷限)
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
| SEC 10-K 抽取 | 任務二 | 側邊欄 → SEC 10-K |
| 瀏覽器代理 | 任務一 | 側邊欄 → Browser Agent |
| 評估儀表板 | KPI + CSV + 即時紀錄 | 側邊欄 → Eval |

部署關鍵環境變數見下方 [設定與環境變數](#設定與環境變數)。

---

## 專案結構

```
whaleforce-coding-test/
├── streamlit_app.py        # 入口：載入 .env、註冊 4 個頁面、側邊欄環境檢查
├── pages/                  # Streamlit 頁面
│   ├── 0_Home.py           #   總覽 / 架構圖 / 技術棧
│   ├── 1_SEC_10K.py        #   任務二 UI：抽取 + 結果展示 + 下載
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
│       ├── manifest.json   #   4 份 filing（MSFT/INTC/Citi train + BRK.B heldout）
│       ├── gold/           #   train 的 gold 邊界標註
│       └── cache/          #   離線 CI 用的 EDGAR HTML 快取
├── shared_harness/         # 跨任務共用基礎設施（見下表）
├── prompts/                # 版本化 prompt（v1_*.txt）+ SOP（sops/*.md）+ 迭代紀錄
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
| `llm_router.py` | litellm 封裝：Tier1/2 主用 + 一次性 fallback、預算檢查、成本紀錄、schema 解析 |
| `llm_config.py` | Tier → 模型 ID 對應（可用環境變數覆寫） |
| `llm_parse.py` | 跨廠商 JSON 正規化（剝掉 ```` ```json ```` 圍欄後解析成 Pydantic） |
| `cost_tracker.py` | 執行緒安全成本統計 + 熔斷器（全域 $20 / 每代理執行 $0.50 / 每份財報 $0.30 + 呼叫次數上限） |
| `job_store.py` | SQLite（WAL 模式）：紀錄 runs / steps / cost events，預設 `data/whaleforce.db` |
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
5. **恢復（Recovery）**：導覽失敗時按失敗類型走「策略表」，**不做盲目重試**，每步最多 2 個策略。
6. **卡死偵測**：連續 3 次 `type` 但 URL 沒變 → 判定失敗。
7. **可選終局把關**：`ENABLE_BLIND_CRITIC=true` 時，額外用一個「盲審」LLM 獨立判斷結果是否可信。

### 支援的動作類型（LLM 可規劃）

`click`（點擊）、`type`（輸入，搜尋任務會自動按 Enter 送出）、`scroll`（捲動）、`press_key`（按鍵）、`navigate`（導覽）、`none`（無操作/結束）。

執行器（`browser.py`）基於同步 Playwright + 無頭 Chromium；會在導覽前拒絕 PDF / 下載類 URL，並嘗試關閉常見的 cookie 同意橫幅。

### 恢復策略：按「失敗類型」對症下藥

`recovery.py` 用 `FailureType` 列舉把失敗歸類，再查 `STRATEGY_TABLE` 取對應策略（如捲動、返回上一頁、延長等待），而不是一律重試。這是「確定性 SOP」的體現——邏輯寫死在程式碼裡，由 L1 測試守護。

### 評估任務（`task1_agent/eval/tasks.yaml`）

共 8 個任務：5 個 train + 3 個 heldout。最新一輪 train 結果：**5/5 成功，靜默失敗（silent_failure）= 0**。

| 站點 | 任務類型 | 狀態 | 說明 |
|---|---|---|---|
| example.com | navigate | ✅ Train | 標題驗證，2 步 |
| news.ycombinator.com | extract | ✅ Train | 抽取頭條標題 |
| github.com | navigate | ✅ Train | LLM 規劃導覽到 `/python/cpython` |
| httpbin.org | extract | ✅ Train | 抽取請求標頭（無頭環境偶有時序波動） |
| wikipedia.org | search | ✅ Train | 多步搜尋；輸入後自動 Enter 送出 |
| duckduckgo.com | search | ⚠️ Heldout | 無頭環境同意頁/SERP 不穩定，僅 UI 示範，不計入 KPI |
| sec.gov | navigate | ⚠️ Heldout | EDGAR 搜尋，不在 train 評估內 |
| httpbin.org/forms | form | ⚠️ Heldout | POST 表單，未專門調校 |

---

## 任務二：SEC 10-K 抽取

### 它在做什麼

10-K 是美國上市公司的年度報告，法定結構為 Part I–IV 下的 Item 1～16（如 Item 1 業務、Item 1A 風險因素、Item 7 MD&A、Item 8 財務報表等）。本管線從原始 HTML 中把每個 Item 精確切分出來，並保證 **零幻覺**：輸出文字必須是原文的子字串。

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
- **交叉引用索引（cross-reference index）**：像 INTC 這類非標準格式的 10-K，會用一張「Item → 頁碼」索引表，例如「Item 1. Business … Pages 3-4, 13」。這類短小且以頁碼為主的條目會被 `is_page_reference_text` 辨識為交叉引用，UI 上以「（交叉引用）」標註並引導使用者查看官方原文，而不是把索引列當成內文展示。
- **銀行 TOC 索引列（裸頁碼）**：像 Citi 這類 filing 在開頭有一大段「Item 標題 + 裸頁碼範圍（如 70–129, 174–178）」的目錄列，內文卻只用章節標題（如 `MARKET RISK`、`Report of Independent…`）而不再寫 `Item 7A`。管線會：(1) 辨識裸頁碼索引列；(2) 動態偵測 TOC 區塊；(3) 捨棄 TOC stub 並改用章節名 / 替代標題錨點（如 `Market Risk\nOverview` → Item 7A）定位真實內文。

### 範例 filing

| 公司 | Accession | 特點 / 表現 |
|---|---|---|
| **MSFT** | `0000950170-24-087843` | 6.8 MB iXBRL、標準 TOC，22 個 Item 全數抽取，$0.00 |
| **INTC** | `0000050863-25-000009` | 重度 iXBRL + 交叉引用索引；部分 Item 為頁碼索引（見上） |
| **Citi (C)** | `0000831001-25-000067` | 大型銀行 TOC + incorporated by reference；Item 7/7A/8 需跳過 TOC 索引列，7A 走 `Market Risk\nOverview` 替代標題 |
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
  - 全域 `required_items = ["1","1A","7","8"]`，`gold_items = ["1","1A","1B","1C","7","8","10","14"]`；Citi 覆寫為 `["1A","7","8"]`。
- **Agent**：讀 `task1_agent/eval/tasks.yaml` → 真正啟動 Playwright 跑任務 → 紀錄成功率、步數、延遲、成本。
- **產物**（`reports/`）：
  - `eval_train.csv`：SEC + 代理統一指標（評估頁展示，git 追蹤）。
  - `eval_summary.json`：P50/P95、成本、成功率等彙總 KPI。
  - `heldout_snapshot.json`：BRK.B heldout 快照（**不用於調參**）。
  - `baseline_comparison.json`：regex-only vs 樸素 LLM vs 混合方案的對比。

評估頁（Eval）支援「📂 載入存檔結果」（瞬間顯示已提交基線）與「重跑」兩種方式。

---

## Eval Set 選樣理由與侷限

目前 train 集 3 檔 + heldout 1 檔，**刻意覆蓋不同格式變異**，但也必須誠實說明侷限：

| Filing | 代表的變異維度 | 走到的程式路徑 |
|---|---|---|
| **MSFT** | 標準 iXBRL、規矩 Item 標題 | TOC + regex（happy path） |
| **INTC** | 交叉引用索引格式（Item → 頁碼） | regex + `is_page_reference_text` |
| **Citi** | 金融業、超大 TOC、incorporated by reference、裸頁碼索引 | section_name 替代標題 + TOC stub 清除 |
| **BRK.B**（heldout） | K-1 式 TOC 變體 | section_name |

**共同點（也是盲點）**：全是 2024–2025 近期檔、超大型股、主流申報工具產生的 iXBRL。以下變異軸**尚未納入** eval，但已在 Future Work / 擴充計畫中討論：

- 舊式 pre-iXBRL 純 HTML（2007–2010 `<font>`/table 排版）
- 小型股 / Smaller Reporting Company（雜亂 HTML、精簡揭露）
- REIT / 礦業（Item 4 Mine Safety 有真實內容）
- 10-K/A 修正件（Part III 補件、其餘 item 合法缺漏）
- 同公司跨年度格式漂移（縱向對照）

**已知 eval 方法論限制**：gold 邊界由管線輸出再生成（循環）；`required_items` 只看狀態是否 `extracted`，不量測內容品質——因此我們同時用 span/token/header 契約與手動 spot-check（如 Citi 7A 從 98 字 TOC 列修正為 14 萬字真實 `MARKET RISK` 內文）來補足。

---

## 分析報告：效能、成本、擴充性與正確性驗證

> 以下為摘要數字；完整分析（baseline 對比、失敗模式分析 FMA、可觀測性、held-out 快照、應用場景）見 **[docs/analysis.md](docs/analysis.md)**。數字取自 `reports/eval_summary.json` 與 `reports/eval_train.csv`。

### 效能與成本（實測）

| 指標 | 任務二 SEC 10-K | 任務一 瀏覽器代理 |
|---|---|---|
| 樣本 | 3 份 train filing | 5 個 train 任務 |
| 成功 / 召回 | 必需項 100%（MSFT/INTC 4/4、Citi 3/3） | 成功率 100%（5/5） |
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

此外有 **baseline 對比**（regex-only vs 樸素 LLM vs 本混合管線：必需項召回 66.7% / 50% / **100%**，成本 $0 / $3.17 / **$0**）佐證設計取捨；代理端則以 **L0 每步驗證 + 可選 Blind Critic** 防止「成功卻沒結果」的靜默失敗。`task2_sec/eval/gold/` 的 gold 檔承認是循環產生（由管線輸出再生成），故契約才是真正的品質保證。

### 擴充性（Scalability）

- **更多文件類型**：三層分段 + 章節名對應可推廣到 10-Q / 8-K / 20-F；新增 filing 只需擴充 manifest 與章節標題表，管線無 ticker 特判。
- **吞吐與限速**：`edgar_client` 統一限速 + HTML 快取，可安全批次抓取；`job_store`（SQLite WAL）記錄每次 run / step / 成本事件，便於稽核與離線重跑。
- **成本隨難度自適應**：易解項留在 Tier0（$0），難解項才升級 Tier1/Tier2，避免「一律呼叫大模型」的成本爆炸（延伸方向見 Future Work 的熵梯度路由）。
- **部署**：單一 Docker / Streamlit 多頁，水平複製即可擴充；目前單容器限制單次並行代理執行（記憶體考量，見已知限制）。

---

## 測試

分三層（marker 見 `pytest.ini`），約 118 個測試函式：

```bash
pytest -m unit          # L1：確定性，零 LLM、零網路（約 99 個）
pytest -m integration   # L2：mock 整合（約 12 個）
pytest -m eval          # L3：SEC manifest + 代理任務（較慢，用快取）
```

CLI 評估指令稿：

```bash
python scripts/run_eval.py --split train      # SEC → reports/eval_train.csv
python scripts/run_agent_eval.py              # SEC + 代理實跑 → CSV + summary
python scripts/run_heldout_snapshot.py        # BRK.B heldout（僅本地）
python scripts/demo_circuit_breaker.py        # 預算熔斷示範
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
| 架構與計畫 | Cursor | PLAN.md、prompts/ |
| 10-K 分段 / 指標 | Cursor（TDD） | `test_bs4_anchor.py`、`test_regex_boundary_fallback.py` |
| 代理恢復設計 | Cursor + PLAN | `recovery.py` + `prompts/sops/recovery.md` |
| 評估設計 | Cursor | `manifest.json`、`tasks.yaml` |
| 除錯迭代 | Cursor | `prompts/ITERATION.md`（v1→v2，附測試證據） |

詳細的「失敗路徑 → 解決 → 驗證」敘事見 [prompts/ITERATION.md](prompts/ITERATION.md)；更深入的分析與權衡見 [docs/analysis.md](docs/analysis.md)。

---

## License

MIT（可按需調整）。
