# Topic 更新任務 — AI 執行規則

本文件規範 AI 在更新醫檢師國考題庫 Topic 分析報告時的行為與 SOP。
請在開始工作前，完整閱讀本文件與 `topic分析撰寫指引.txt`。

---

## 身份

你是負責更新醫檢師國考題庫 Topic 分析報告的 AI 助手。你的任務是根據參考資料，撰寫或擴充 Topic 分析報告。

---

## 絕對禁止事項

1. ❌ **禁止直接修改 `_topics/` 資料夾內的文件**（必須透過驗證腳本部署）
2. ❌ **禁止修改任何題目文件**（Question files，即年份資料夾中的 `.md` 檔）
3. ❌ **禁止修改 YAML 區塊中 `type`、`subject`、`definition`、`is_pinned`、`aliases` 的值**
4. ❌ **禁止修改或省略 Dataview 區塊**（文件末尾的 ` ```dataview ` 區塊）
5. ❌ **禁止更改檔名**
6. ❌ **禁止一次處理多個 Topic**（每次只處理一個）
7. ❌ **禁止在 `data_MD_update` 以外的地方建立或修改任何文件**
8. ❌ **絕對禁止刪減舊報告中的知識點、表格列/欄、以及 Anki 卡片**（只能新增或擴充）

---

## 執行 SOP

### Step 0: 首次執行準備（僅第一次需要）

1. 閱讀本文件（`AGENTS.md`）
2. 閱讀 `topic分析撰寫指引.txt`，了解撰寫標準
3. 若 `topic_list.csv` 不存在，執行：
   ```
   python data_MD_update/01_generate_topic_list.py
   ```

### Step 1: 準備參考資料

執行以下指令：

```
python data_MD_update/02_prepare_ai_reference.py
```

此腳本會自動：
- 選擇最優先的 `Pending`（或恢復中斷的 `InProgress`）Topic
- 備份舊文件至 `old_MD/` 資料夾
- 產生 `reference_for_ai.txt`
- 在 `topic_list.csv` 中標記該 Topic 為 `InProgress`

### Step 2: 閱讀參考資料

閱讀 `data_MD_update/reference_for_ai.txt`，其中包含：
- 基本資訊（Topic 名稱、科目、題數、是否為 Stub）
- **YAML 區塊**（必須原封不動複製到新文件開頭）
- **Dataview 區塊**（必須原封不動複製到新文件結尾）
- 舊 Topic 文件內容（擴充更新的基礎）
- 所有題目（標記 `[已納入]` 或 `[新題目]`）

### Step 3: 撰寫新 Topic 文件

根據 `topic分析撰寫指引.txt` 的規範撰寫新版 Topic 文件。

**新文件的結構必須為：**

```markdown
---
type: topic
subject: {從參考資料複製}
definition: {從參考資料複製}
is_pinned: {從參考資料複製}
aliases: {從參考資料複製}
---

## 類群定義

> {定義內容}

---

## 類群說明

## 核心趨勢與高頻考點

{分析內容...}

## 未來考點預測與易混淆陷阱

{分析內容...}

## 關鍵字反射表

{表格...}

## Anki 聯想卡

```Anki
{卡片內容...}
```

---

## 包含題庫

```dataview
{從參考資料原封不動複製}
```
```

**將新文件存至**（路徑在 `reference_for_ai.txt` 的「基本資訊」中有指定）：

```
data_MD_update/new_MD/{subject}/{topic_name}.md
```

### Step 4: 執行驗證

```
python data_MD_update/03_validate_and_deploy.py --validate-only
```

- **通過**：Topic 狀態變為 `Validated`，繼續 Step 5
- **失敗**：
  1. 閱讀錯誤訊息
  2. 修正 `new_MD/` 中的文件
  3. 將 `topic_list.csv` 中該 Topic 的 Status 改回 `InProgress`
  4. 重新執行驗證

### Step 5: 繼續下一個 Topic

若尚未達到本次更新的目標數量（預設 5 個），回到 **Step 1**。

若已完成目標數量或 quota 即將耗盡，向使用者報告：
- 已完成的 Topic 列表
- `topic_list.csv` 中各 Topic 的狀態
- 提醒使用者執行 `03_validate_and_deploy.py --deploy-all` 進行批量部署

---

## 重要提醒

### 關於 Stub Topic

若 `reference_for_ai.txt` 中標示「文件類型: 全新生成」，表示此 Topic 尚無分析內容。
你需要**根據所有題目從零開始撰寫**完整的分析報告，而非在現有內容上擴充。

### 關於 Quota 耗盡

若你的 quota 即將耗盡而無法完成當前 Topic：
1. 儘量將已完成的部分存至 `new_MD/`（即使不完整）
2. 告知使用者目前進度
3. 下一個 AI 執行 Step 1 時，`02_prepare_ai_reference.py` 會自動恢復中斷的 Topic

### 關於格式嚴格要求

- Anki 卡片格式：`問題;<ans>答案</ans><br><br>📌補充說明`
- Anki 卡片必須在 ` ```Anki ` 和 ` ``` ` 之間
- 表格使用 Markdown 格式，欄位用 `|` 分隔
- 關鍵字用粗體 `**粗體**` 強調
- 視覺特徵附上 Google 圖片搜尋連結：`[🖼️](https://www.google.com/search?q=keyword&tbm=isch&udm=2)`
- 專業術語可以用 `#關鍵字` Obsidian 內文標籤標記
