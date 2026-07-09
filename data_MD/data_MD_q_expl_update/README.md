# data_MD_q_expl_update — 考題詳解自動生成工作流程

自動化為 `data_MD/` 中的醫檢師考題生成「筆記與詳解」段落的完整 Pipeline。

透過 pyautogui 影像辨識 + 擬人化滑鼠操作，驅動 Chrome 內建的 Gemini 側邊欄，逐題讀取題目內容、送出 Prompt、等待回應、複製結果、驗證品質、最終部署回原始 Markdown 檔案中。

---

## 工作流程概覽

```
┌───────────────────────────────┐
│  01_generate_question_list.py │  掃描 data_MD/，產生待處理清單 CSV
└──────────┬────────────────────┘
           ▼
┌────────────────────────────────┐
│  02_auto_gemini_explanation.py │  主腳本：自動化 Gemini 生成詳解
│  (pyautogui + Gemini Sidebar)  │
└──────────┬─────────────────────┘
           │  每題自動呼叫 ▼
┌───────────────────────────────┐
│  03_validate.py               │  驗證回應品質，通過後部署回 MD
└───────────────────────────────┘
```

---

## 前置需求

- **作業系統**：Windows（依賴 `winsound`、`pydirectinput` 等 Windows 專用模組）
- **Python 套件管理**：[uv](https://docs.astral.sh/uv/)
- **瀏覽器**：Chrome（需開啟 Gemini 側邊欄功能）
- **螢幕解析度**：影像辨識模板以特定解析度截圖，若解析度不同需重新截圖

---

## 各腳本說明

### 01_generate_question_list.py

掃描 `data_MD/` 下的所有科目資料夾，解析每份 Markdown 考題的 frontmatter，產生一份 CSV 清單 (`question_list.csv`) 記錄所有題目的處理狀態。

**執行方式：**
```bash
uv run python 01_generate_question_list.py
```

**輸出**：`question_list.csv`，欄位包含：
| 欄位 | 說明 |
|------|------|
| `filename` | 檔案名稱（如 `5_115-1_1.md`）|
| `subject` | 科目名稱 |
| `year` | 年份（如 `115-1`）|
| `exam_id` | 考卷編號 |
| `question_number` | 題號 |
| `difficulty` | 難度（來自 frontmatter）|
| `relative_path` | 相對於 `data_MD/` 的路徑 |
| `status` | 處理狀態：`Pending` / `InProgress` / `Completed` / `Failed` / `Skipped` |
| `model_used` | 使用的 Gemini 模型（`flash` / `pro`）|
| `error_msg` | 錯誤訊息（若失敗）|

**狀態說明**：
- `Pending`：尚未處理
- `Skipped`：已有「筆記與詳解」內容（不需處理）
- `InProgress`：正在處理中
- `Completed`：處理完成
- `Failed`：處理失敗

---

### 02_auto_gemini_explanation.py

核心自動化腳本。讀取 CSV 中 `Pending` / `Failed` / `InProgress` 的題目，逐題執行以下步驟：

1. **開啟 Gemini 側邊欄** (`Alt+G`)
2. **開新對話** (避免上下文污染)
3. **選擇模型** (依難度自動選 Flash 或 Pro) + 啟用延長思考
4. **輸入 Prompt** (透過 Gemini Skill 或直接貼入完整 Prompt)
5. **送出** 並驗證 Skill 是否成功觸發
6. **等待生成完成** → 捲動至底部 → 複製回應
7. **驗證品質** (呼叫 `03_validate.py`)
8. **部署回原始 MD** 或標記失敗

**執行方式：**
```bash
uv run --with pyautogui --with pydirectinput --with pyperclip --with pygetwindow \
       --with opencv-python --with pillow \
       python 02_auto_gemini_explanation.py [OPTIONS]
```

**可用參數：**
| 參數 | 說明 |
|------|------|
| `--manual-send` | 不自動送出 Prompt，等待使用者手動按下送出 |
| `--start-from FILENAME` | 從指定的檔案名稱開始處理（跳過之前的題目）|
| `--dry-run` | 僅列出待處理的題目清單，不實際執行 |
| `--auto-git` | 啟用定時自動 git 備份功能（commit + push）|
| `--commit-interval SECONDS` | 自動備份間隔秒數（預設 `3600` = 1 小時），需搭配 `--auto-git` |

**模型選擇邏輯**：
- 難度為「適中」「困難」「非常困難」→ Gemini Pro + 延長思考
- 其他 → Gemini Flash + 延長思考

**Quota 額度管理**：
- 偵測到 Gemini 使用額度耗盡時，自動切換 Google 帳號繼續執行
- 支援兩個帳號輪替
- 若兩個帳號都耗盡，會嘗試解析恢復時間並自動等待

**自動 Git 備份 (`--auto-git`)**：
- 啟動時先執行 `git ls-remote` 驗證 GitHub 憑證是否有效；若過期會立刻彈出登入視窗
- 每到達 `--commit-interval` 後，在題目間的 cooldown 期間自動執行：
  1. `git add data_MD/` — 僅 stage `data_MD/` 的變更
  2. `git commit` — 附帶時間戳、完成題數、失敗題數
  3. `git pull --rebase` — 同步遠端變更（避免覆蓋線上修改）
  4. `git push` — 推送至 GitHub
- 若 pull 發生衝突，自動 `git rebase --abort` 取消同步，不影響主流程
- 所有題目處理完畢 / 連續失敗中止時，也會執行一次最終備份
- `Ctrl+C` 手動中止時不執行 git 操作

---

### 03_validate.py

驗證 Gemini 回應品質並部署至原始檔案的模組。通常由 `02` 腳本自動呼叫。

**驗證項目**：
| 檢查代碼 | 說明 |
|---------|------|
| CHECK-0 | 原始檔案是否包含 `## 筆記與詳解` 段落 |
| CHECK-1 | 題目文本（`## 筆記與詳解` 之前的內容）未被修改 |
| CHECK-2 | 詳解中不包含 `<br><br>` |
| CHECK-3 | 新檔案大小增加至少 100 字元 |
| CHECK-4 | 詳解內容不為空 |
| CHECK-5 | YAML Frontmatter 未被修改 |

通過所有檢查後，會自動將新內容寫回原始 MD 檔案。

---

### _utils.py

共享工具模組，提供：
- 路徑常數（`DATA_ROOT`、`IMAGE_DIR`、`CSV_FILENAME` 等）
- CSV 讀寫函式（`read_question_list`、`write_question_list`、`update_question_status`）
- 輕量級 YAML Frontmatter 解析器（不依賴 PyYAML）
- Markdown 內容解析工具

---

## 目錄結構

```
data_MD_q_expl_update/
├── 01_generate_question_list.py   # 步驟 1：產生題目清單
├── 02_auto_gemini_explanation.py   # 步驟 2：自動化 Gemini 生成
├── 03_validate.py                  # 步驟 3：驗證 & 部署
├── _utils.py                       # 共享工具模組
├── question_list.csv               # 題目清單（自動產生）
├── images_AG/                      # pyautogui 影像辨識用的螢幕截圖模板
│   ├── gemini_input_box.png
│   ├── gemini_send_btn.png
│   ├── gemini_copy_btn.png
│   ├── ... (共 25 張)
├── old_temp/                       # 驗證用暫存（原始版本）
├── new_temp/                       # 驗證用暫存（新版本）
└── README.md                       # 本文件
```

---

## 典型使用流程

```bash
# 1. 產生/更新題目清單
uv run python 01_generate_question_list.py

# 2. 確認待處理題目數量
uv run --with pyautogui --with pydirectinput --with pyperclip --with pygetwindow --with opencv-python --with pillow python 02_auto_gemini_explanation.py --dry-run

# 3. 開始自動化生成（含自動 Git 備份，每小時同步一次）
uv run --with pyautogui --with pydirectinput --with pyperclip --with pygetwindow --with opencv-python --with pillow python 02_auto_gemini_explanation.py --auto-git

# 4. 從指定題目開始、不啟用自動備份
uv run --with pyautogui --with pydirectinput --with pyperclip --with pygetwindow --with opencv-python --with pillow python 02_auto_gemini_explanation.py --start-from 5_115-1_1.md
```

---

## 注意事項

- 執行 `02` 腳本時，**請勿移動滑鼠或操作鍵盤**，否則會干擾影像辨識和擬人化操作流程。
- 若 `images_AG/` 中的截圖模板與實際畫面不符（例如更換螢幕解析度、Chrome 更新介面），需重新截圖替換。
- `--auto-git` 備份僅限 `data_MD/` 目錄，不會影響專案其他資料夾。
