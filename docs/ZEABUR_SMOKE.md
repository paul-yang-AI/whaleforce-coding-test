# Zeabur Smoke Checklist（手動 + 已跑過的自動項）

**站點：** https://whaleforce-coding-test.zeabur.app  
**前置：** Zeabur 已 redeploy 最新 `master`；`GEMINI_API_KEY` + `SEC_USER_AGENT` 在控制台已設（側邊欄應為 ✅）。

---

## 已自動驗證（本地，2026-06-01）

| 檢查 | 結果 |
|------|------|
| `python scripts/e2e_smoke.py` | 6/6 PASS |
| `python scripts/run_private_regression.py --skip-pytest --skip-smoke` | SEC 3/3、held-out 6/8、agent 3/5 |
| `reports/eval_train.csv` | 8 列（3 SEC + 5 agent） |
| `reports/heldout_baseline.json` | tier0 6/8，`with_llm` 8 筆 |
| Zeabur `/_stcore/health` | HTTP **200** |

以下需在瀏覽器逐項勾選（約 15–25 分鐘）。

---

## 手動步驟（對照 SUBMISSION.md）

### Browser Agent

1. 側邊欄 → **瀏覽器代理**
2. **Example.com**：預設「導航至 Example.com」→ **執行** → 等完成 → **重新整理**  
   - [ ] `success` + **結果** 區塊有文字
3. **Hacker News**：預設「頭條標題」→ **執行**  
   - [ ] 多步（2–3 步）、Result 有標題（非空）

### SEC 10-K

4. 側邊欄 → **SEC 10K** → **基準集（Train · 3）**
5. **MSFT** → **抽取**  
   - [ ] 頂部 **Required KPI 4/4**
6. **INTC** 或 **Citi** → **抽取**  
   - [ ] **3/3**
7. **Citi** 再確認（可選）  
   - [ ] 1A/7/8、9A/9B 長正文；Item 10–14 incorporated；front 索引 honest missing
8. **泛化驗證（Held-out · 8）** → **JPM** → **抽取**  
   - [ ] 能跑完；Required **4/4** 或 KPI 通過
9. 任一分頁抽完後 → **JSON / Markdown 下載**  
   - [ ] 幾乎即時下載

### Browser Agent 泛化

10. **瀏覽器代理** → **泛化驗證（Held-out）**  
    - [ ] 列表 5 任務；徽章顯示 **3/5** 預期（forms、python_docs、quotes）

### Eval

11. 側邊欄 → **Eval** → **基準評估 Train** → **📂 載入存檔結果**  
    - [ ] KPI：SEC 3/3、Agent 5/5；左 SEC 三卡、右 Agent 五卡
12. **🔬 Held-out 基線**  
    - [ ] SEC 表 6/8；下方 Agent 表 3/5；可見 `with_llm` 小表
13. **🔴 即時執行紀錄**（若剛跑過任務）  
    - [ ] 可見 Agent / SEC runs

---

## 失敗時速查

| 現象 | 可能原因 |
|------|----------|
| 側邊欄 API ❌ | Zeabur 未設 `GEMINI_API_KEY` / `SEC_USER_AGENT` |
| Agent `plan_failed` | Gemini quota / key 錯 |
| SEC 抽取失敗 | `SEC_USER_AGENT` 缺失或 SEC 429 |
| Eval Agent 卡片空白 | 未 redeploy 含 `eval_train.csv` 的 commit；按「重跑完整基準」 |
| Citi 很慢 | 正常（大 HTML），等 1–2 分鐘 |

---

## 本地重現指令

```powershell
.venv\Scripts\python.exe scripts\e2e_smoke.py
.venv\Scripts\python.exe scripts\run_private_regression.py --skip-pytest --skip-smoke
curl.exe -s -o NUL -w "%{http_code}" https://whaleforce-coding-test.zeabur.app/_stcore/health
```
