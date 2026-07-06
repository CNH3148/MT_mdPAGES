# data_MD_update 使用說明

本資料夾提供一套半自動化的 Topic 分析報告更新流程，搭配 AI 助手使用。
透過腳本處理資料蒐集、備份與驗證，AI 只需專注於閱讀題目和撰寫報告。

---

## 快速開始

### 前置準備

1. 將本資料夾 (`data_MD_update`) 放入 `data_MD/` 資料夾內
2. 確認 `topic分析撰寫指引.txt` 已存在於本資料夾中
3. 確認已安裝 Python 3.10+（無需額外套件）

最終目錄結構：

```
data_MD/
├── data_MD_update/        ← 本資料夾
│   ├── AGENTS.md
│   ├── README.md
│   ├── topic分析撰寫指引.txt
│   ├── _utils.py
│   ├── 01_generate_topic_list.py
│   ├── 02_prepare_ai_reference.py
│   └── 03_validate_and_deploy.py
├── 生物化學與臨床生化學/
├── 臨床血液學與血庫學/
└── ...
```

### 首次使用：產生更新清單

```bash
cd data_MD                      # 進入 data_MD 資料夾
uv run python data_MD_update/01_generate_topic_list.py
```

這會掃描所有 6 大科目共 215 個 Topic，計算優先度，並產生 `topic_list.csv`。

---

## 使用流程

### 方式一：交給 AI 自動執行（推薦）

1. 開啟一個新的 AI 對話（如 Gemini、Claude 等有檔案存取權限的 AI）
2. 輸入以下指令：

   ```
   請閱讀 data_MD_update/AGENTS.md，然後按照指示開始工作。
   ```

3. AI 會自動循環處理 Topic（預設 5 個或 quota 耗盡前）：
   - 執行準備腳本 → 讀取參考資料 → 撰寫新文件 → 執行驗證
4. AI 完成後，**由你手動確認並部署**：

   ```bash
   python data_MD_update/03_validate_and_deploy.py --deploy-all
   ```

### 方式二：手動逐步操作

```bash
# Step 1: 準備參考資料（自動選擇最優先的 Topic）
uv run python data_MD_update/02_prepare_ai_reference.py

# Step 2: 讓 AI 閱讀 reference_for_ai.txt 並撰寫新文件到 new_MD/

# Step 3: 驗證新文件
uv run python data_MD_update/03_validate_and_deploy.py --validate-only

# Step 4: 確認無誤後部署
python data_MD_update/03_validate_and_deploy.py --deploy-all
```

---

## 各腳本說明

### `01_generate_topic_list.py` — 產生更新清單

| 項目 | 說明 |
|---|---|
| 功能 | 掃描資料庫，計算每個 Topic 的更新優先度 |
| 輸出 | `topic_list.csv` |
| 何時執行 | 首次使用時；或想重新計算優先度時 |

**優先度公式**：`0.5 × (總題數 / 80) + 0.5 × (1 - 支持度)`

- 總題數越多 → 優先度越高（該 Topic 的考試重要性高）
- 支持度越低 → 優先度越高（越多新題目尚未被納入分析）

### `02_prepare_ai_reference.py` — 準備參考資料

| 項目 | 說明 |
|---|---|
| 功能 | 備份舊文件、產生 AI 所需的參考資料 |
| 輸出 | `reference_for_ai.txt` + `old_MD/{subject}/` 備份 |
| 何時執行 | 每個 Topic 更新前執行一次 |

**智慧選擇**：自動挑選 `InProgress`（恢復中斷）或最高優先 `Pending` 的 Topic。

### `03_validate_and_deploy.py` — 驗證與部署

| 模式 | 指令 | 說明 |
|---|---|---|
| 僅驗證 | `--validate-only` | 驗證通過後標記為 `Validated`，不部署 |
| 批量部署 | `--deploy-all` | 部署所有 `Validated` 的 Topic |
| 單次模式 | （無旗標） | 驗證 + 立即部署當前 Topic |

**驗證項目（共 8 項）**：
1. 新文件存在
2. YAML `type` 一致
3. YAML `subject` 一致
4. `definition` 欄位存在
5. `is_pinned` 欄位存在
6. `aliases` 欄位存在
7. Dataview 區塊逐字比對
8. 檔名一致

**部署成功後自動執行**：
- 將新文件覆寫回 `_topics/` 資料夾
- 部署後二次驗證
- 將該 Topic 所有題目的 `summarize_including` 更新為 `true`
- 更新 `topic_list.csv` 狀態為 `Completed`

### `04_auto_gemini_update.py` — 透過 API 全自動更新

| 項目 | 說明 |
|---|---|
| 功能 | 結合 `02`、Google Gemini API 及 `03` 腳本，實現無人值守的全自動 Topic 更新 |
| 前提 | 需在腳本內設定有效的 Google Gemini API Key |
| 何時執行 | 當你想讓腳本直接利用 API 處理整個更新流程時執行 |

### `05_watch_dumps.py` — 自動監聽與部署輔助

| 項目 | 說明 |
|---|---|
| 功能 | 監聽 `new_MD/dumps/`，自動將手動放入的 MD 檔案歸檔至對應科目，並自動驗證、部署與準備下一題 |
| 前提 | 適合在網頁版 AI（如 Google AI Studio）手動生成內容時搭配使用 |
| 何時執行 | 執行後讓它常駐背景，當你把做好的新檔案丟進 `dumps/` 時，它會自動幫你收尾並準備下一題 |

---

## 狀態流程

```
Pending → InProgress → Validated → Completed
              ↓              ↓
           (中斷)         (Failed)
              ↓
        下次自動恢復
```

| 狀態 | 意義 |
|---|---|
| `Pending` | 尚未開始 |
| `InProgress` | AI 正在處理中（或中斷後等待恢復）|
| `Validated` | 已通過驗證，等待手動部署 |
| `Completed` | 已成功部署回資料庫 |
| `Failed` | 驗證或部署失敗，錯誤原因記錄在 `Note` 欄 |

---

## 中斷恢復

如果 AI 的 quota 耗盡導致任務中斷：

1. 被中斷的 Topic 狀態為 `InProgress`
2. 開啟新的 AI 對話，重複「交給 AI 自動執行」的步驟
3. `02_prepare_ai_reference.py` 會自動偵測並恢復中斷的 Topic
4. 已有的備份不會被覆蓋

---

## 資料夾結構

```
data_MD_update/
├── AGENTS.md                  ← AI 讀取的執行規則
├── README.md                  ← 本說明文件
├── topic分析撰寫指引.txt        ← 撰寫標準（你提供的）
│
├── _utils.py                  ← 共用工具模組
├── 01_generate_topic_list.py  ← 產生清單
├── 02_prepare_ai_reference.py ← 準備參考資料
├── 03_validate_and_deploy.py  ← 驗證與部署
├── 04_auto_gemini_update.py   ← API 自動更新腳本
├── 05_watch_dumps.py          ← 自動監聽 dumps 腳本
│
├── topic_list.csv             ← [自動產生] 更新清單
├── reference_for_ai.txt       ← [自動產生] AI 參考資料
│
├── old_MD/                    ← [自動建立] 舊文件備份
│   └── {subject}/{topic}.md
└── new_MD/                    ← [AI 寫入] 新文件暫存
    ├── dumps/                 ← [手動丟入] 手動生成時的暫存區
    └── {subject}/{topic}.md
```

---

## 常見問題

### Q: 我想重新計算優先度怎麼辦？

刪除 `topic_list.csv` 後重新執行 `01_generate_topic_list.py`。
注意：已完成的 Topic 狀態會被重置為 `Pending`。

### Q: 驗證失敗怎麼辦？

1. 查看 `topic_list.csv` 中的 `Note` 欄了解錯誤原因
2. 修正 `new_MD/` 中的文件
3. 將 `topic_list.csv` 中該 Topic 的 `Status` 改回 `InProgress`
4. 重新執行驗證腳本

### Q: 我想要跳過某個特定的 Topic（例如該主題目前沒有任何題目），該怎麼做？

1. 打開 `topic_list.csv`。
2. 搜尋並找到您想跳過的 Topic 所在的行數。
3. 將該行的 `Status` 欄位值從 `InProgress` 或是 `Pending` 更改為 `Completed`（您也可以在最後的 `Note` 欄位加註 "Skipped" 方便日後辨識）。
4. 存檔關閉後，重新執行一次 `02_prepare_ai_reference.py`，系統就會自動忽略它並抓取下一個優先級最高的主題。

### Q: 我想撤銷一個已部署的 Topic？

舊文件備份在 `old_MD/{subject}/{topic_name}.md`。
手動將備份檔複製回 `{subject}/_topics/` 即可還原。

### Q: 腳本需要安裝任何套件嗎？

不需要。所有腳本僅使用 Python 標準庫（無外部依賴）。
