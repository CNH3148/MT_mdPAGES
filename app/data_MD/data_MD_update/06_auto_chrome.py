"""
06_auto_chrome.py — Google AI Studio 全自動化腳本 (Chrome CDP 遠端接管版)

功能：
  1. 監聽 reference_for_ai.txt 的更新
  2. 自動開啟全新對話串並設定所有參數
  3. 貼上 Prompt 並以 Ctrl+Enter 送出
  4. 等待模型生成完畢後提取 Markdown
  5. 將結果存入 dumps/ 資料夾

前置條件：
  - 透過以下指令啟動 Chrome (必須先關閉所有 Chrome 視窗):
    & "$env:LOCALAPPDATA\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\\ChromeDevSession"
  - 在該 Chrome 中登入 Google AI Pro 帳號
  - 確保 Google AI Studio 中已有名為 "topic分析撰寫指引" 的 System Instruction preset

使用方式：
  uv run --with playwright --with pyperclip python data_MD_update/06_auto_chrome.py

暫停方式：
  直接在終端按 Ctrl+C 即可安全中止
"""
import sys
import time
import logging
import winsound
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
    import pyperclip
    import pyautogui
    import pygetwindow as gw
except ImportError:
    print("請使用: uv run --with playwright --with pyperclip --with pyautogui --with pygetwindow python data_MD_update/06_auto_chrome.py")
    sys.exit(1)

# ── 設定 ──────────────────────────────────────────────────
DATA_ROOT = Path("C:/Users/star0/Desktop/data_MD/data_MD_update")
REF_FILE = DATA_ROOT / "reference_for_ai.txt"
DUMPS_DIR = DATA_ROOT / "new_MD" / "dumps"
DUMPS_DIR.mkdir(parents=True, exist_ok=True)

WAIT_SECONDS = 120  # 等待模型生成的秒數
POLL_INTERVAL = 2   # 監聽 reference_for_ai.txt 的間隔秒數

# ── 日誌 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)
sys.stdout.reconfigure(encoding='utf-8')


# ── 工具函式 ──────────────────────────────────────────────
def extract_topic_name(ref_text: str) -> str:
    """從 reference_for_ai.txt 中提取 Topic 名稱。"""
    for line in ref_text.splitlines():
        if "Topic 名稱" in line:
            parts = line.split(":", 1)
            if len(parts) > 1:
                return parts[1].strip()
    return "output"


def wait_for_new_reference(last_mtime: float) -> float:
    """阻塞等待 reference_for_ai.txt 出現新版本。"""
    log.info("監聽 reference_for_ai.txt 的更新...")
    while True:
        if REF_FILE.exists():
            current_mtime = REF_FILE.stat().st_mtime
            if current_mtime > last_mtime:
                time.sleep(2)  # 確保寫入完成
                return current_mtime
        time.sleep(POLL_INTERVAL)


# ── 核心自動化流程 ────────────────────────────────────────
def setup_new_chat(page) -> bool:
    """
    在全新的 new_chat 頁面上設定所有參數。
    回傳 True 表示成功，False 表示失敗。
    """
    # Step 0: Navigate to new chat
    log.info("[Step 0] 導航至全新對話串...")
    try:
        # 👑 關鍵修正：避免使用 page.goto 造成硬重整 (這會破壞 SPA 狀態並導致主題變成淺色)
        # 改為優先點擊畫面上的「New chat」按鈕
        new_chat_btn = page.get_by_role('button', name='New chat')
        if new_chat_btn.count() > 0:
            new_chat_btn.first.click(timeout=3000)
            log.info("[Step 0] ✅ 已點擊 'New chat' 按鈕 (保留 SPA 狀態)")
        else:
            log.warning("[Step 0] 找不到 'New chat' 按鈕，退回使用網址導航...")
            page.goto("https://aistudio.google.com/prompts/new_chat", timeout=60000)
        
        # 等待網路靜止，確保換頁完成
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as e:
        log.warning(f"[Step 0] 導航出現異常: {e}，重試一次...")
        page.goto("https://aistudio.google.com/prompts/new_chat", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(2)

    # Step 1: Select System Instructions preset
    log.info("[Step 1] 選擇 System Instructions preset...")
    try:
        sys_btn = page.get_by_role('button', name='System instructions')
        sys_btn.click(timeout=5000)
        time.sleep(1)

        combos = page.get_by_role('combobox').all()
        for c in combos:
            text = c.inner_text(timeout=2000).strip()
            if 'Create new instruction' in text:
                c.click(timeout=3000)
                time.sleep(1)
                page.get_by_role('option', name='topic分析撰寫指引').click(timeout=3000)
                time.sleep(1)
                break

        # 關閉模態對話框
        page.keyboard.press("Escape")
        time.sleep(1)
        log.info("[Step 1] ✅ System Instructions 設定完成")
    except Exception as e:
        log.error(f"[Step 1] ❌ 失敗: {e}")
        return False

    # Step 2: Ensure Advanced settings is expanded
    log.info("[Step 2] 確認 Advanced settings 已展開...")
    try:
        # 新頁面預設就是展開的，所以先檢查 Media resolution 是否已存在
        already_visible = page.evaluate('''() => {
            let el = document.querySelector('[aria-label="Media resolution"]');
            return el !== null;
        }''')
        if already_visible:
            log.info("[Step 2] ✅ Advanced settings 已展開 (Media resolution 可見)")
        else:
            # 如果不存在才點擊展開
            adv_btn = page.get_by_role('button', name='Expand or collapse advanced settings')
            adv_btn.click(timeout=5000)
            time.sleep(3)
            log.info("[Step 2] ✅ 手動展開成功")
    except Exception as e:
        log.error(f"[Step 2] ❌ 失敗: {e}")
        return False

    # Step 3: Set Media resolution to High (with retry)
    log.info("[Step 3] 設定 Media resolution → High...")
    media_ok = False
    for attempt in range(3):
        try:
            # 先用 JS 滾動到元素位置
            found = page.evaluate('''() => {
                let el = document.querySelector('[aria-label="Media resolution"]');
                if (el) {
                    el.scrollIntoView({ behavior: 'instant', block: 'center' });
                    return true;
                }
                return false;
            }''')
            if not found:
                log.warning(f"[Step 3] 第 {attempt+1} 次嘗試: 元素尚未出現，等待中...")
                time.sleep(3)
                # 再次嘗試滾動整個設定面板
                page.evaluate('''() => {
                    let area = document.querySelector('.scrollable-area');
                    if (area) area.scrollTop = area.scrollHeight;
                }''')
                time.sleep(2)
                continue

            time.sleep(1)
            media_select = page.get_by_label('Media resolution')
            current = media_select.inner_text(timeout=5000).strip()
            if current != 'High':
                media_select.click(timeout=3000, force=True)
                time.sleep(0.5)
                page.get_by_role('option', name='High').click(timeout=3000)
                time.sleep(0.5)
            log.info(f"[Step 3] ✅ Media resolution = {media_select.inner_text().strip()}")
            media_ok = True
            break
        except Exception as e:
            log.warning(f"[Step 3] 第 {attempt+1} 次嘗試失敗: {e}")
            time.sleep(2)
    if not media_ok:
        log.error("[Step 3] ❌ Media resolution 設定失敗 (3 次嘗試均失敗)")
        return False

    # Step 4: Verify Thinking level
    log.info("[Step 4] 驗證 Thinking level...")
    try:
        thinking_select = page.get_by_label('Thinking Level')
        current = thinking_select.inner_text().strip()
        if current != 'High':
            thinking_select.click(timeout=3000)
            time.sleep(0.5)
            page.get_by_role('option', name='High').click(timeout=3000)
            time.sleep(0.5)
        log.info(f"[Step 4] ✅ Thinking level = {thinking_select.inner_text().strip()}")
    except Exception as e:
        log.error(f"[Step 4] ❌ 失敗: {e}")
        return False

    # Step 5: Verify Model
    log.info("[Step 5] 驗證模型...")
    try:
        model_card = page.locator('.model-selector-card')
        model_text = model_card.inner_text().strip()
        if 'gemini-3.1-pro-preview' not in model_text.lower():
            log.warning("[Step 5] 模型不正確，嘗試切換...")
            model_card.click(timeout=3000)
            time.sleep(1)
            page.get_by_text('gemini-3.1-pro-preview', exact=True).click(timeout=3000)
            time.sleep(1)
        log.info("[Step 5] ✅ Model = gemini-3.1-pro-preview")
    except Exception as e:
        log.error(f"[Step 5] ❌ 失敗: {e}")
        return False

    # Step 6: Grounding & URL context
    log.info("[Step 6] 驗證 Grounding 與 URL context...")
    try:
        if page.get_by_role('button', name='Remove Grounding with Google Search').count() == 0:
            page.get_by_role('button', name='Open tools menu').click(timeout=3000)
            time.sleep(1)
            page.get_by_text('Grounding with Google Search').click(timeout=3000)
            time.sleep(0.5)
        log.info("[Step 6] ✅ Grounding is ON")
    except Exception as e:
        log.error(f"[Step 6] Grounding 錯誤: {e}")
        return False

    try:
        if page.get_by_role('button', name='Remove URL context').count() == 0:
            add_url = page.get_by_role('button', name='Add suggested tool: URL context')
            if add_url.count() > 0:
                add_url.click(timeout=3000)
                time.sleep(0.5)
            else:
                page.get_by_role('button', name='Open tools menu').click(timeout=3000)
                time.sleep(1)
                page.locator('label.tool-label:has-text("URL context")').click(timeout=3000)
                time.sleep(0.5)
                page.keyboard.press("Escape")
                time.sleep(0.5)
        log.info("[Step 6] ✅ URL context is ON")
    except Exception as e:
        log.error(f"[Step 6] URL context 錯誤: {e}")
        return False

    return True

def submit_prompt(page, ref_text: str) -> bool:
    """將 Prompt 貼入對話框並送出，支援失敗自動重試。"""
    log.info("[送出] 準備透過 OS 原生事件全自動貼上並送出...")
    try:
        # 將字串放入剪貼簿
        pyperclip.copy(ref_text)
        
        # 尋找 Chrome 視窗並帶到最上層
        windows = [w for w in gw.getAllWindows() if 'Google AI Studio' in w.title or 'Chrome' in w.title]
        if windows:
            win = windows[0]
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(1)
        else:
            log.warning("[送出] 找不到 Chrome 視窗，將嘗試直接輸出鍵盤事件...")

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            log.info(f"[送出] 第 {attempt} 次嘗試送出...")
            
            # 取得輸入框絕對螢幕座標 (考慮 Windows DPI 縮放比例)
            box_coords = page.evaluate('''() => {
                let el = document.querySelector('rich-textarea') || document.querySelector('textarea');
                if (!el) return null;
                let rect = el.getBoundingClientRect();
                let chromeHeight = window.outerHeight - window.innerHeight;
                let chromeWidth = window.outerWidth - window.innerWidth;
                let cssX = window.screenX + (chromeWidth / 2) + rect.left + rect.width / 2;
                let cssY = window.screenY + chromeHeight + rect.top + rect.height / 2;
                let ratio = window.devicePixelRatio || 1;
                return {x: cssX * ratio, y: cssY * ratio};
            }''')
            
            if box_coords:
                # 模擬人類滑鼠移動軌跡 (花費 0.6 秒移動)，避免被判定為機器人瞬間移動
                pyautogui.moveTo(box_coords['x'], box_coords['y'], duration=0.6)
                time.sleep(0.2)
                pyautogui.click()
                time.sleep(1)
            else:
                log.warning("[送出] 找不到輸入框座標，退回 Playwright focus()")
                prompt_box = page.get_by_label('Enter a prompt')
                prompt_box.focus()
                time.sleep(1)

            # 先全選並刪除 (確保前一次失敗的殘留文字被清空)
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.5)
            pyautogui.press('delete')
            time.sleep(0.5)

            # 貼上文字 (模擬人類按鍵延遲)
            pyautogui.keyDown('ctrl')
            time.sleep(0.1)
            pyautogui.press('v')
            time.sleep(0.1)
            pyautogui.keyUp('ctrl')
            time.sleep(2)
            
            # 取得送出按鈕座標並使用實體滑鼠點擊 (比 Ctrl+Enter 更像人類)
            send_coords = page.evaluate('''() => {
                let btn = document.querySelector('button.ctrl-enter-submits');
                if (!btn) {
                    let btns = Array.from(document.querySelectorAll('button'));
                    btn = btns.find(b => b.textContent && b.textContent.trim().startsWith('Run'));
                }
                if (!btn) return null;
                let rect = btn.getBoundingClientRect();
                let chromeHeight = window.outerHeight - window.innerHeight;
                let chromeWidth = window.outerWidth - window.innerWidth;
                let cssX = window.screenX + (chromeWidth / 2) + rect.left + rect.width / 2;
                let cssY = window.screenY + chromeHeight + rect.top + rect.height / 2;
                let ratio = window.devicePixelRatio || 1;
                return {x: cssX * ratio, y: cssY * ratio};
            }''')
            
            if send_coords:
                # 模擬人類滑鼠移動軌跡
                pyautogui.moveTo(send_coords['x'], send_coords['y'], duration=0.5)
                time.sleep(0.2)
                pyautogui.click()
            else:
                log.warning("[送出] 找不到送出按鈕座標，退回 Ctrl+Enter")
                pyautogui.hotkey('ctrl', 'enter')
            
            log.info("[送出] 已點擊送出，等待 8 秒檢查是否報錯...")
            time.sleep(8)
            
            # 檢查是否有報錯訊息 (不管是 Internal error 還是 Permission denied)
            error_internal = page.get_by_text("An internal error has occurred", exact=False)
            error_permission = page.get_by_text("Permission denied", exact=False)
            
            if error_internal.count() > 0 or error_permission.count() > 0:
                log.warning(f"[送出] ⚠️ 第 {attempt} 次送出被擋下 (偵測到錯誤訊息)，準備重試...")
                # 嘗試關閉錯誤訊息框 (如果有打叉按鈕)
                try:
                    close_btn = page.get_by_role("button", name="Close", exact=False)
                    if close_btn.count() > 0:
                        close_btn.first.click(timeout=1000)
                except Exception:
                    pass
                time.sleep(2)
                continue  # 進入下一次迴圈重試
            else:
                log.info("[送出] ✅ Prompt 已全自動送出，未偵測到錯誤！")
                return True

        log.error(f"[送出] ❌ 嘗試了 {max_retries} 次全自動送出依然被擋下。")
        # 降級回半自動模式，讓人類親自接手
        winsound.Beep(1000, 500)
        print("\n\a" + "🔔" * 25)
        print("👉 [手動介入] 全自動送出失敗，請回到 Chrome 視窗「親自」操作！")
        print("👉 請點擊輸入框，按下 Ctrl+A -> Delete -> Ctrl+V -> 送出！")
        print("\n💬 確認「已經成功送出，且模型正在生成或已完成」後，")
        input("   請回到此終端機按下 [Enter] 鍵，腳本會立刻接手後續的等待與提取...")
        print("🔔" * 25 + "\n")
        return True

    except Exception as e:
        log.error(f"[送出] ❌ 異常: {e}")
        return False


def wait_and_extract(page) -> str | None:
    """等待模型生成完畢，然後提取 Markdown 內容。"""
    log.info(f"[等待] 等待模型生成 ({WAIT_SECONDS} 秒)...")
    for remaining in range(WAIT_SECONDS, 0, -1):
        mins, secs = divmod(remaining, 60)
        sys.stdout.write(f"\r  ⏳ 剩餘: {mins:02d}:{secs:02d} ")
        sys.stdout.flush()
        time.sleep(1)
    print()  # 換行

    log.info("[提取] 嘗試提取生成的 Markdown...")

    # 檢查是否出現權限錯誤或內部錯誤
    try:
        has_error = page.evaluate('''() => {
            let text = document.body.innerText.toLowerCase();
            return text.includes('permission denied') || text.includes('an internal error') || text.includes('failed to generate');
        }''')
        if has_error:
            log.error("[提取] ❌ 發現模型生成錯誤 (Permission denied / Internal Error)")
            return None
    except Exception as e:
        log.warning(f"[提取] 錯誤檢查失敗: {e}")

    # 方法 A: 嘗試點擊三點選單 → Copy with Markdown
    try:
        # 模型回覆的選單標籤是 Open options (而非 View more actions)
        more_buttons = page.locator('[aria-label="Open options"]').all()
        if more_buttons:
            last_more = more_buttons[-1]
            last_more.click(timeout=3000, force=True)
            time.sleep(1)

            copy_md = page.get_by_text('Copy as Markdown', exact=False)
            if copy_md.count() == 0:
                copy_md = page.get_by_text('Copy with Markdown', exact=False)

            if copy_md.count() > 0:
                copy_md.first.click(timeout=3000, force=True)
                time.sleep(1)
                md_text = pyperclip.paste()
                if md_text and len(md_text) > 100:
                    log.info(f"[提取] ✅ 方法 A 成功！(長度: {len(md_text)})")
                    
                    # 為了避免 Windows 寫檔時發生 \r\n 變成 \r\r\n，這裡統一洗掉 \r
                    md_text = md_text.replace("\r", "")
                    # 修復 AI Studio Markdown 匯出時會將所有換行加倍 (\n\n) 的問題 (這會破壞表格渲染)
                    md_text = md_text.replace("\n\n", "\n")
                    
                    # 去除可能包含的 Markdown 語法外框或多餘前綴 (例如 "模型產出：\n")
                    # 尋找第一個 "---" (YAML 的開頭)
                    start_idx = md_text.find("---")
                    if start_idx != -1:
                        md_text = md_text[start_idx:]
                    
                    # 去除可能包含的結尾 Markdown 語法 (例如 "```")
                    md_text = md_text.strip()
                    if md_text.endswith("```"):
                        md_text = md_text[:-3].strip()
                        
                    return md_text
                else:
                    log.warning("[提取] 方法 A 剪貼簿內容太短，改用方法 B")
            else:
                log.warning("[提取] 找不到 'Copy with Markdown' 按鈕，改用方法 B")
                page.keyboard.press("Escape")
                time.sleep(0.5)
    except Exception as e:
        log.warning(f"[提取] 方法 A 失敗: {e}")

    # 方法 B: 透過 DOM 提取最後一個回覆的文字內容
    try:
        md_text = page.evaluate('''() => {
            // 嘗試多種可能的選擇器
            let selectors = [
                'message-content.model-response-text',
                'ms-chat-turn.model-turn .turn-content',
                '.model-response-text',
                'message-content',
                '.response-container'
            ];
            for (let sel of selectors) {
                let elements = document.querySelectorAll(sel);
                if (elements.length > 0) {
                    return elements[elements.length - 1].innerText;
                }
            }
            return '';
        }''')
        if md_text and len(md_text) > 100:
            log.info(f"[提取] ✅ 方法 B 成功！(長度: {len(md_text)})")
            
            # 為了避免 Windows 寫檔時發生 \r\n 變成 \r\r\n，這裡統一洗掉 \r
            md_text = md_text.replace("\r", "")
            # 修復 AI Studio Markdown 匯出時會將所有換行加倍 (\n\n) 的問題 (這會破壞表格渲染)
            md_text = md_text.replace("\n\n", "\n")
            
            # 去除可能包含的 Markdown 語法外框或多餘前綴 (例如 "模型產出：\n")
            # 尋找第一個 "---" (YAML 的開頭)
            start_idx = md_text.find("---")
            if start_idx != -1:
                md_text = md_text[start_idx:]
            
            # 去除可能包含的結尾 Markdown 語法 (例如 "```")
            md_text = md_text.strip()
            if md_text.endswith("```"):
                md_text = md_text[:-3].strip()
            
            return md_text
    except Exception as e:
        log.warning(f"[提取] 方法 B 失敗: {e}")

    log.error("[提取] ❌ 所有方法均失敗")
    return None


# ── 主迴圈 ────────────────────────────────────────────────
def main():
    print("=" * 58)
    print("  Google AI Studio 全自動化腳本 (Chrome CDP 遠端接管版)")
    print("  暫停: Ctrl+C")
    print("=" * 58)

    with sync_playwright() as p:
        try:
            log.info("正在連線到 Chrome (localhost:9222)...")
            # 👑 最關鍵的修復：加入 no_defaults=True
            # Playwright 預設連線時會強制注入一些 Emulation 參數（例如強制設定淺色模式、強制重設焦點行為等）。
            # 這些 CDP Emulation 指令會觸發 Google AI Studio 伺服器的反爬蟲機制 (Recaptcha / Bot Detection)，
            # 導致我們最後按下 Run 的時候，伺服器因為偵測到環境被模擬，而無情地回傳 Permission denied。
            # 加上 no_defaults=True，Playwright 就「完全不會」去動瀏覽器的任何原生設定（完美保持深色模式），
            # 也就是說，Google 的後端完全看不出這跟您親自操作有什麼差別！
            browser = p.chromium.connect_over_cdp("http://localhost:9222", no_defaults=True)
        except Exception:
            log.error("無法連線到 Chrome！請確認您已透過以下指令啟動:")
            log.error('  & "$env:LOCALAPPDATA\\Google\\Chrome\\Application\\chrome.exe" '
                      '--remote-debugging-port=9222 --user-data-dir="C:\\ChromeDevSession"')
            return

        contexts = browser.contexts
        if not contexts or not contexts[0].pages:
            log.error("找不到可用的瀏覽器頁面。")
            return

        page = contexts[0].pages[0]
        log.info(f"✅ 已連線: {page.title()}")

        last_mtime: float = 0
        if REF_FILE.exists():
            last_mtime = REF_FILE.stat().st_mtime - 10  # 第一次立刻觸發

        while True:
            try:
                current_mtime = wait_for_new_reference(last_mtime)
                # 👑 關鍵修正 1：讀取檔案時確保使用 Windows 標準的 \r\n 換行符號
                # 如果只用 \n，在貼上到 Google AI Studio 時可能會被視為單一巨大段落，導致後端模型 API 解析失敗 (Internal Error)
                with open(REF_FILE, "r", encoding="utf-8", newline="") as f:
                    ref_text = f.read()
                ref_text = ref_text.replace('\r\n', '\n').replace('\n', '\r\n')
                
                topic_name = extract_topic_name(ref_text)
                is_fix_prompt = ref_text.startswith("[FIX_PROMPT]")

                log.info(f"{'='*58}")
                if is_fix_prompt:
                    log.info(f">>> 收到 [FIX_PROMPT] 原地修正指令！")
                else:
                    log.info(f">>> 開始處理 Topic: {topic_name}")
                log.info(f"{'='*58}")

                # 設定所有參數 (只有新題目才需要開新對話)
                if not is_fix_prompt:
                    if not setup_new_chat(page):
                        log.error(f"設定失敗，將在 10 秒後重試...")
                        time.sleep(10)
                        continue

                    log.info("[同步] 等待所有設定儲存至伺服器...")
                    try:
                        # 等待沒有網路活動，確保自動儲存完成
                        page.wait_for_load_state('networkidle', timeout=15000)
                    except Exception:
                        pass
                    time.sleep(5)  # 額外保險等待

                # 送出 Prompt
                if not submit_prompt(page, ref_text):
                    log.error(f"送出失敗，將在 10 秒後重試...")
                    time.sleep(10)
                    continue

                # 等待並提取結果
                md_content = wait_and_extract(page)

                if md_content:
                    out_file = DUMPS_DIR / f"{topic_name}.md"
                    out_file.write_text(md_content, encoding="utf-8")
                    log.info(f"✅ 已存檔: {out_file}")
                    log.info(f"檔案大小: {len(md_content)} 字元")
                    
                    # 只有在完全成功時，才更新 last_mtime，這樣失敗時下一圈會自動重試同一個檔案
                    last_mtime = current_mtime
                else:
                    log.error(f"❌ 無法取得 {topic_name} 的內容，將在 15 秒後重試...")
                    time.sleep(15)

            except KeyboardInterrupt:
                log.info("收到中止訊號，安全退出。")
                break
            except Exception as e:
                log.error(f"未預期的錯誤: {e}")
                time.sleep(5)


if __name__ == "__main__":
    main()
