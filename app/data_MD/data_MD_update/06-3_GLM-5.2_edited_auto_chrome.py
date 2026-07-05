"""
06-3_GLM-5.2_edited_auto_chrome.py — Google AI Studio 全自動化腳本 (OS 影像辨識 + CDP 提取混合版)

運作原理：
  1. 啟動帶有 CDP Port 的 Chrome，但不立刻連線。
  2. 透過 pyautogui 影像辨識完成「設定參數」與「貼上 Prompt 並送出」。
     - 包含側邊欄滾動搜尋、開關按鈕狀態檢測。
  3. 確認送出成功後，才透過 CDP 連線讀取 DOM，提取 Markdown 結果。
"""
import sys
import time
import logging
import winsound
import subprocess
from pathlib import Path

try:
    import pyautogui
    import pyperclip
    import pygetwindow as gw
    from playwright.sync_api import sync_playwright
except ImportError:
    print("請使用: uv run --with playwright --with pyautogui --with pyperclip --with pygetwindow --with opencv-python --with pillow python data_MD_update/06_auto_chrome.py")
    sys.exit(1)

# ── 設定 ──────────────────────────────────────────────────
DATA_ROOT = Path("C:/Users/star0/Desktop/data_MD/data_MD_update")
REF_FILE = DATA_ROOT / "reference_for_ai.txt"
DUMPS_DIR = DATA_ROOT / "new_MD" / "dumps"
IMAGE_DIR = DATA_ROOT / "images"

DUMPS_DIR.mkdir(parents=True, exist_ok=True)

WAIT_SECONDS = 120
POLL_INTERVAL = 2

CHROME_PATH = r"C:\Users\star0\AppData\Local\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = r"C:\ChromeDevSession"
AI_STUDIO_URL = "https://aistudio.google.com/prompts/new_chat"

pyautogui.PAUSE = 0.5
pyautogui.FAILSAFE = True

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)
sys.stdout.reconfigure(encoding='utf-8')


# ── OS 工具函式 ───────────────────────────────────────────
def extract_topic_name(ref_text: str) -> str:
    for line in ref_text.splitlines():
        if "Topic 名稱" in line:
            parts = line.split(":", 1)
            if len(parts) > 1:
                return parts[1].strip()
    return "output"

def wait_for_new_reference(last_mtime: float) -> float:
    log.info("監聽 reference_for_ai.txt 的更新...")
    while True:
        if REF_FILE.exists():
            current_mtime = REF_FILE.stat().st_mtime
            if current_mtime > last_mtime:
                time.sleep(2)
                return current_mtime
        time.sleep(POLL_INTERVAL)

def get_chrome_window():
    windows = [w for w in gw.getAllWindows() if 'Google AI Studio' in w.title or 'Chrome' in w.title]
    return windows[0] if windows else None

def activate_chrome():
    win = get_chrome_window()
    if win:
        try:
            if win.isMinimized: 
                win.restore()
            win.activate()
        except Exception as e:
            # pygetwindow 常見的 Bug: Error code from Windows: 0
            if "Error code from Windows: 0" not in str(e):
                log.warning(f"視窗啟動警告 (不影響執行): {e}")
        time.sleep(0.5)

def find_and_click(img_name, confidence=0.8, timeout=5):
    """尋找按鈕並點擊中心"""
    img_path = IMAGE_DIR / f"{img_name}.png"
    if not img_path.exists():
        log.warning(f"缺少截圖: {img_path}")
        return False
        
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            location = pyautogui.locateCenterOnScreen(str(img_path), confidence=confidence)
            if location:
                pyautogui.moveTo(location.x, location.y, duration=0.3)
                pyautogui.click()
                return True
        except pyautogui.ImageNotFoundException:
            pass
        except Exception:
            pass
        time.sleep(1)
    return False

def find_and_click_right_edge(img_name, confidence=0.8, timeout=3):
    """尋找按鈕並點擊最右側 1/3 處 (用於開關按鈕)"""
    img_path = IMAGE_DIR / f"{img_name}.png"
    if not img_path.exists():
        log.warning(f"缺少截圖: {img_path}")
        return False

    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            box = pyautogui.locateOnScreen(str(img_path), confidence=confidence)
            if box:
                # 點擊右側 1/3 區域
                click_x = box.left + int(box.width * 0.85)
                click_y = box.top + int(box.height / 2)
                pyautogui.moveTo(click_x, click_y, duration=0.3)
                pyautogui.click()
                return True
        except pyautogui.ImageNotFoundException:
            pass
        except Exception:
            pass
        time.sleep(1)
    return False

def check_image_exists(img_name, confidence=0.8, timeout=3):
    """檢查特定狀態的圖片是否存在於畫面上"""
    img_path = IMAGE_DIR / f"{img_name}.png"
    if not img_path.exists():
        return False

    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            if pyautogui.locateOnScreen(str(img_path), confidence=confidence):
                return True
        except:
            pass
        time.sleep(0.5)
    return False

def scroll_and_find(img_name, confidence=0.8, max_scrolls=5):
    """在右側側邊欄向下滾動並尋找目標按鈕"""
    screen_w, screen_h = pyautogui.size()
    # 將滑鼠移到右側側邊欄區域 (大約螢幕寬度的 80% 處)
    sidebar_x = int(screen_w * 0.8)
    sidebar_y = int(screen_h * 0.5)
    pyautogui.moveTo(sidebar_x, sidebar_y, duration=0.3)
    
    for attempt in range(max_scrolls + 1):
        # 先檢查目前畫面有沒有
        if find_and_click(img_name, confidence=confidence, timeout=1):
            return True
        
        if attempt < max_scrolls:
            log.info(f"找不到 {img_name}，向下滾動側邊欄 (第 {attempt+1} 次)...")
            # 在 Windows 上，scroll 單位通常較大 (例如 120 是一個刻度)，-5 太小了
            pyautogui.scroll(-500)
            time.sleep(1)
    
    return False

def human_takeover(reason: str):
    log.error(f"❌ 自動化失敗: {reason}")
    winsound.Beep(1000, 500)
    print("\n" + "🔔" * 20)
    print(f"👉 [需要手動介入] {reason}")
    input("   完成後，回到此終端機按下 [Enter] 鍵繼續執行...")
    print("🔔" * 20 + "\n")

# ── OS 核心流程 (設定與送出) ──────────────────────────────
def setup_new_chat_os():
    log.info("[Step 0] 重新整理網頁以清除上一回合的 CDP 痕跡...")
    activate_chrome()
    pyautogui.press('f5')
    time.sleep(8)
    
    log.info("[Step 0] 開啟全新對話串...")
    if not find_and_click("new_chat_btn", confidence=0.7, timeout=10):
        raise Exception("找不到 New chat 按鈕")
    time.sleep(3)

    log.info("[Step 1] 設定 System Instructions...")
    if not find_and_click("sys_instruction_btn", timeout=5):
        raise Exception("找不到 System instructions 按鈕")
    
    if find_and_click("sys_dropdown", timeout=3):
        if not find_and_click("topic_preset", timeout=3):
            raise Exception("找不到 'topic分析撰寫指引' 選項")
        time.sleep(1)
        if not find_and_click("sys_close_btn", timeout=3):
            log.warning("找不到關閉按鈕 (叉叉)，嘗試按 Escape 關閉")
            pyautogui.press('escape')
        time.sleep(1)
    else:
        log.info("[Step 1] 找不到下拉選單，可能已預設套用 preset")
    time.sleep(1)

    log.info("[Step 2] 設定 Media resolution...")
    if scroll_and_find("media_resolution_btn", confidence=0.7):
        if not find_and_click("media_high_option", timeout=3):
            raise Exception("找不到 Media High 選項")
        pyautogui.press('escape')
    else:
        raise Exception("捲動到底仍找不到 Media resolution 按鈕")
    time.sleep(1)

    # log.info("[Step 3] 設定 Thinking level...")
    # if scroll_and_find("thinking_level_btn", confidence=0.7):
    #     if not find_and_click("thinking_high_option", timeout=3):
    #         raise Exception("找不到 Thinking High 選項")
    #     pyautogui.press('escape')
    # else:
    #     raise Exception("捲動到底仍找不到 Thinking level 按鈕")
    # time.sleep(1)

    # log.info("[Step 4] 設定 Grounding with Google Search...")
    # if scroll_and_find("grounding_off", confidence=0.7):
    #     log.info("Grounding 目前為關閉，點擊右側開啟...")
    #     find_and_click_right_edge("grounding_off", timeout=2)
    # elif check_image_exists("grounding_on", confidence=0.7):
    #     log.info("✅ Grounding 已經是開啟狀態")
    # else:
    #     raise Exception("找不到 Grounding 按鈕")
    # time.sleep(1)

    log.info("[Step 5] 設定 URL context...")
    if scroll_and_find("url_context_off", confidence=0.7):
        log.info("URL context 目前為關閉，點擊右側開啟...")
        find_and_click_right_edge("url_context_off", timeout=2)
    elif check_image_exists("url_context_on", confidence=0.7):
        log.info("✅ URL context 已經是開啟狀態")
    else:
        raise Exception("找不到 URL context 按鈕")
    time.sleep(1)

    log.info("✅ 側邊欄參數設定流程完畢")

def submit_prompt_os(ref_text: str) -> bool:
    log.info("[送出] 準備透過純 OS 事件貼上並送出...")
    activate_chrome()
    pyperclip.copy(ref_text)
    
    if not find_and_click("input_box", confidence=0.7, timeout=10):
        raise Exception("找不到輸入框")
    
    pyautogui.keyDown('ctrl')
    time.sleep(0.1)
    pyautogui.press('a')
    time.sleep(0.1)
    pyautogui.keyUp('ctrl')
    time.sleep(0.3)
    pyautogui.press('delete')
    time.sleep(0.5)
    
    pyautogui.keyDown('ctrl')
    time.sleep(0.1)
    pyautogui.press('v')
    time.sleep(0.1)
    pyautogui.keyUp('ctrl')
    time.sleep(2)
    
    if not find_and_click("run_btn", confidence=0.8, timeout=10):
        log.warning("找不到 Run 按鈕，嘗試 Ctrl+Enter...")
        pyautogui.keyDown('ctrl')
        time.sleep(0.1)
        pyautogui.press('enter')
        time.sleep(0.1)
        pyautogui.keyUp('ctrl')
    
    log.info("[送出] ✅ 已送出 Prompt (OS 模擬)")
    return True

def check_submit_success() -> bool:
    """送出後 5 秒，短暫連線 CDP 確認是否報錯。"""
    log.info("[驗證] 連線 CDP 檢查是否送出成功...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://localhost:9222", no_defaults=True)
            page = browser.contexts[0].pages[0]
            
            error_internal = page.get_by_text("An internal error has occurred", exact=False)
            error_permission = page.get_by_text("Permission denied", exact=False)
            
            if error_internal.count() > 0 or error_permission.count() > 0:
                log.error("[驗證] ❌ 偵測到報錯訊息！")
                return False
            log.info("[驗證] ✅ 未偵測到錯誤，模型正在生成")
            return True
    except Exception as e:
        log.error(f"[驗證] CDP 連線失敗: {e}")
        return False


# ── 提取流程 (純 OS 影像辨識) ─────────────────────────
def wait_and_extract_os() -> str | None:
    log.info(f"[等待] 等待模型生成 ({WAIT_SECONDS} 秒)...")
    for remaining in range(WAIT_SECONDS, 0, -1):
        mins, secs = divmod(remaining, 60)
        sys.stdout.write(f"\r  ⏳ 剩餘: {mins:02d}:{secs:02d} ")
        sys.stdout.flush()
        time.sleep(1)
    print()
    
    log.info("[提取] 嘗試透過 OS 影像辨識提取生成的 Markdown...")
    activate_chrome()
    
    screen_w, screen_h = pyautogui.size()
    
    # 1. 移動到畫面正中央懸停，讓選單出現
    log.info("[提取] 移動滑鼠至畫面正中央懸停...")
    pyautogui.moveTo(screen_w // 2, screen_h // 2, duration=0.5)
    time.sleep(1.5) 
    
    # 2. 尋找畫面上所有的三點按鈕
    img_path = IMAGE_DIR / "model_options_btn.png"
    if not img_path.exists():
        raise Exception("找不到 model_options_btn.png 截圖")
    else:
        # 尋找所有匹配的三點按鈕
        log.info("[提取] 掃描畫面上的三點按鈕...")
        boxes = list(pyautogui.locateAllOnScreen(str(img_path), confidence=0.7))
        
        if not boxes:
            raise Exception("畫面上找不到任何三點按鈕")
        
        # 3. 找出 Y 座標最大的 (最底部/最後一個模型回覆)
        target_box = max(boxes, key=lambda b: b.top)
        
        # 因為圖片包含了三個按鈕，我們要點擊最右側的那個，所以 X 座標取 left + width * (5/6)
        click_x = target_box.left + int(target_box.width * 5 / 6)
        click_y = target_box.top + int(target_box.height / 2)
        
        log.info(f"[提取] 找到最後一個三點按鈕群組，點擊最右側 1/3 座標: ({click_x}, {click_y})")
        pyautogui.moveTo(click_x, click_y, duration=0.3)
        pyautogui.click()
        time.sleep(1)
    
    # 4. 尋找 Copy as Markdown 按鈕
    if not find_and_click("copy_as_markdown", confidence=0.7, timeout=5):
        raise Exception("找不到 copy_as_markdown 按鈕")
    
    time.sleep(1)
    
    # 5. 讀取剪貼簿
    md_text = pyperclip.paste()
    if md_text and len(md_text) > 100:
        log.info(f"[提取] ✅ 成功！(長度: {len(md_text)})")
        md_text = md_text.replace("\r", "").replace("\n\n", "\n")
        start_idx = md_text.find("---")
        if start_idx != -1:
            md_text = md_text[start_idx:]
        md_text = md_text.strip()
        if md_text.endswith("```"):
            md_text = md_text[:-3].strip()
        return md_text
    
    log.error("[提取] ❌ 剪貼簿內容為空或太短")
    return None


# ── 主程式 ────────────────────────────────────────────────
def main():
    print("=" * 58)
    print("  Google AI Studio (OS 影像辨識 + CDP 提取混合版)")
    print("  緊急中止: 將滑鼠快速移到螢幕最左上角")
    print("=" * 58)

    log.info("啟動 Chrome (帶 CDP Port，但暫不連線)...")
    subprocess.Popen([
        CHROME_PATH,
        f"--user-data-dir={USER_DATA_DIR}",
        AI_STUDIO_URL
    ])
    time.sleep(10)
    activate_chrome()

    last_mtime: float = time.time()
    if REF_FILE.exists():
        last_mtime = REF_FILE.stat().st_mtime

    while True:
        try:
            current_mtime = wait_for_new_reference(last_mtime)
            with open(REF_FILE, "r", encoding="utf-8", newline="") as f:
                ref_text = f.read()
            ref_text = ref_text.replace('\r\n', '\n').replace('\n', '\r\n')
            
            topic_name = extract_topic_name(ref_text)
            is_fix_prompt = ref_text.startswith("[FIX_PROMPT]")

            log.info(f"{'='*58}")
            log.info(f">>> 開始處理 Topic: {topic_name}")
            log.info(f"{'='*58}")

            if not is_fix_prompt:
                for attempt in range(1, 4):
                    try:
                        setup_new_chat_os()
                        time.sleep(3)
                        submit_prompt_os(ref_text)
                        break  # 如果這兩步都沒有觸發 human_takeover (拋出例外)，就跳出迴圈
                    except Exception as e:
                        if attempt < 3:
                            log.warning(f"❌ 第 {attempt} 次自動化操作失敗: {e}，5 秒後重試...")
                            time.sleep(5)
                        else:
                            human_takeover(f"自動化操作失敗已達 3 次: {e}")
            else:
                # 若是 FIX_PROMPT，只執行送出
                for attempt in range(1, 4):
                    try:
                        submit_prompt_os(ref_text)
                        break
                    except Exception as e:
                        if attempt < 3:
                            log.warning(f"❌ 第 {attempt} 次自動化送出失敗: {e}，5 秒後重試...")
                            time.sleep(5)
                        else:
                            human_takeover(f"自動化送出失敗已達 3 次: {e}")
            
            # 刪除原本呼叫 check_submit_success() 的邏輯，因為連線 CDP 會觸發偵測中斷生成！
            
            md_content = wait_and_extract_os()

            if md_content:
                out_file = DUMPS_DIR / f"{topic_name}.md"
                out_file.write_text(md_content, encoding="utf-8")
                log.info(f"✅ 已存檔: {out_file}")
                last_mtime = current_mtime
            else:
                log.error(f"❌ 無法取得內容，將在 15 秒後重試...")
                time.sleep(15)

        except KeyboardInterrupt:
            log.info("收到中止訊號，安全退出。")
            break
        except Exception as e:
            # 忽略因為 human_takeover 被捕捉而外洩的例外
            if "手動介入" not in str(e):
                log.error(f"未預期的錯誤: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()