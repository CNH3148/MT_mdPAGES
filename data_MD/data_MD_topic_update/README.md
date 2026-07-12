# data_MD_topic_update — Topic 自動化更新工具

## 概述

本工具自動化更新 `data_MD` 中的醫學閃卡 Topic 分析報告（Markdown 格式）。
透過 Google AI Studio 產生新版分析，經本地嚴格驗證後部署回資料庫。

## 快速上手

**重要：** 所有的指令都必須在 `data_MD` 根目錄下執行：
```bash
cd C:\Users\star0\Desktop\data_MD_PAGE\data_MD
```

### 一鍵全自動（推薦）

```bash
# 步驟 1：（首次或需要重新排序時）生成/更新 topic_list.csv
uv run python data_MD_topic_update/01_generate_topic_list.py

# 步驟 2：啟動全自動串聯流程
uv run --with pydirectinput --with pyautogui --with pyperclip --with pygetwindow --with opencv-python --with pillow python data_MD_topic_update/07_auto_update_topics.py
```

### 半自動模式（遭遇 reCAPTCHA 封鎖時）

```bash
uv run ... python data_MD_topic_update/07_auto_update_topics.py --manual-send
```

在此模式下，腳本會完成設定與貼上 prompt，但暫停等你親自點擊 Run 按鈕送出。

### 緊急中止

將滑鼠快速移到**螢幕最左上角**即可觸發 pyautogui FAILSAFE。

---

## 系統架構

```
07_auto_update_topics.py  ← 唯一需要執行的腳本
    │
    ├── 02_prepare_ai_reference.py   呼叫 (subprocess)
    │       讀取 topic_list.csv，選出最高優先題目
    │       備份舊檔 → 產生 reference_for_ai.txt
    │
    ├── 06-4 Chrome 自動化引擎       匯入 (importlib)
    │       擬人化操作 AI Studio → 送出 prompt → 提取生成內容
    │       ├── human_input.py  (貝茲曲線滑鼠、人類 dwell 鍵盤)
    │       └── images/         (影像辨識用截圖)
    │
    └── 03_validate_and_deploy.py    呼叫 (subprocess)
            7 項嚴格驗證 → Dataview 自動接枝 → 部署回 data_MD
```

### 處理流程

```
                    ┌──────────────────────────────────────┐
                    │         07 主迴圈 (while True)        │
                    └──┬───────────────────────────────────┘
                       │
    ┌──────────────────▼──────────────────┐
    │ Step 1: 讀取 CSV，找 Pending 題目    │──── 全部完成 → 結束
    └──────────────────┬──────────────────┘
                       │
    ┌──────────────────▼──────────────────┐
    │ Step 2: 呼叫 02 準備 reference       │
    └──────────────────┬──────────────────┘
                       │
    ┌──────────────────▼──────────────────┐
    │ Step 3: Chrome setup (開新 chat)     │
    └──────────────────┬──────────────────┘
                       │
    ┌──────────────────▼──────────────────┐
    │ Step 4: 送出 Prompt                  │──── 被擋 → 冷卻 → 重試
    └──────────────────┬──────────────────┘
                       │
    ┌──────────────────▼──────────────────┐
    │ Step 5: 等待生成 + 提取 Markdown      │
    └──────────────────┬──────────────────┘
                       │
    ┌──────────────────▼──────────────────┐
    │ Step 6: 呼叫 03 驗證 + 部署          │
    │         Failed → FIX_PROMPT 重送     │
    │         Success → 下一題             │
    └──────────────────┬──────────────────┘
                       │
                  題間冷卻 20-45s
                       │
                 回到 Step 1
```

---

## 腳本一覽

| 腳本 | 用途 | 執行方式 |
|------|------|----------|
| `01_generate_topic_list.py` | 掃描所有科目，生成/更新 `topic_list.csv`（保留既有 Status） | 手動執行 |
| `02_prepare_ai_reference.py` | 選出最高優先題目，產生 `reference_for_ai.txt` | 由 07 自動呼叫 |
| `03_validate_and_deploy.py` | 7 項驗證 + Dataview 接枝 + 部署 | 由 07 自動呼叫 |
| `06-4_GLM-5.2_edited_auto_chrome.py` | Chrome AI Studio 擬人化自動操作引擎 | 由 07 匯入 |
| **`07_auto_update_topics.py`** | **全自動串聯腳本（主程式）** | **使用者執行** |
| `human_input.py` | 擬人化輸入模組（貝茲曲線、人類 dwell） | 被 06-4 匯入 |
| `_utils.py` | 共用工具（CSV、YAML frontmatter、路徑） | 被多個腳本匯入 |

### 排序規則（01 腳本）

優先順序：
1. **題數落差**（`total - included`）越大越優先
2. 若落差相同，**總題數**越多越優先

### 重要檔案

| 檔案 | 說明 |
|------|------|
| `topic_list.csv` | 所有 topic 的狀態追蹤（Priority / Status / Note） |
| `reference_for_ai.txt` | 餵給 AI 的參考資料（由 02 產生） |
| `topic分析撰寫指引.txt` | AI System Instruction 的 preset |
| `setup_actions.json` | Chrome 側邊欄設定步驟 |
| `images/` | 影像辨識用的 UI 截圖 |
| `new_MD/` | 新生成的 Markdown 暫存區 |
| `old_MD/` | 舊版備份 |

---

## 首次使用前準備

1. **關閉所有 Chrome 視窗**（避免 attach 到帶 debug port 的舊 process）
2. 首次以新 profile `C:\ChromeAutoSession` 啟動後，手動**登入 Google AI Pro**
3. 在 AI Studio 設定中建立 System Instruction preset「topic分析撰寫指引」
4. （選用）截 `stop_btn.png` 存到 `images/` 目錄，提升生成偵測準確度

## 封存腳本

`archive_scripts/` 資料夾包含已被 07 取代或僅供除錯用的舊腳本：

- `04_auto_gemini_update.py` — 早期 Gemini API 方案
- `05_watch_dumps.py` — 舊版 dumps 監聽器（已整合入 07）
- `06_auto_chrome.py` — 舊版 CDP 方案
- `06-1/2/3_*.py` — Chrome 自動化的歷代迭代版本
- `HANDOVER.md` — 歷史交接文件
- `test_*.py` / `fix_*.py` / `check_*.py` — 除錯與修復工具
