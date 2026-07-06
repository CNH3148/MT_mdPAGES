"""
06_auto_chrome.py — Google AI Studio 全自動化腳本 (純 OS + 軌跡錄製版)

使用方式：
  1. 第一次使用，先錄製「設定參數」的軌跡：
     uv run ... python 06_auto_chrome.py --record
     (在 Chrome 中完成所有設定後，按下鍵盤 Esc 鍵結束錄製)
  
  2. 正常自動化執行：
     uv run ... python 06_auto_chrome.py
"""
import sys
import time
import json
import logging
import winsound
import argparse
import subprocess
from pathlib import Path

try:
    import pyautogui
    import pyperclip
    import pygetwindow as gw
    from pynput import mouse, keyboard
except ImportError:
    print("請使用: uv run --with pyautogui --with pyperclip --with pygetwindow --with opencv-python --with pillow --with pynput python data_MD_update/06_auto_chrome.py")
    sys.exit(1)

# ── 設定 ──────────────────────────────────────────────────
DATA_ROOT = Path("C:/Users/star0/Desktop/data_MD/data_MD_update")
REF_FILE = DATA_ROOT / "reference_for_ai.txt"
DUMPS_DIR = DATA_ROOT / "new_MD" / "dumps"
IMAGE_DIR = DATA_ROOT / "images"
ACTIONS_FILE = DATA_ROOT / "setup_actions.json"  # 錄製的軌跡檔

DUMPS_DIR.mkdir(parents=True, exist_ok=True)

WAIT_SECONDS = 120
POLL_INTERVAL = 2

CHROME_PATH = r"C:\Users\star0\AppData\Local\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = r"C:\ChromeDevSession"
AI_STUDIO_URL = "https://aistudio.google.com/prompts/new_chat"

pyautogui.PAUSE = 0.3
pyautogui.FAILSAFE = True

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
        if win.isMinimized: win.restore()
        win.activate()
        time.sleep(0.5)
    else:
        log.warning("找不到 Chrome 視窗！")

def find_and_click(img_name, confidence=0.8, timeout=10):
    img_path = IMAGE_DIR / f"{img_name}.png"
    if not img_path.exists():
        log.error(f"找不到截圖: {img_path}")
        return False
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            location = pyautogui.locateCenterOnScreen(str(img_path), confidence=confidence)
            if location:
                pyautogui.moveTo(location.x, location.y, duration=0.3)
                pyautogui.click()
                return True
        except: pass
        time.sleep(1)
    log.warning(f"找不到 {img_name}.png")
    return False

def human_takeover(reason: str) -> bool:
    log.error(f"❌ 自動化失敗: {reason}")
    winsound.Beep(1000, 500)
    print("\n" + "🔔" * 20)
    print(f"👉 [需要手動介入] {reason}")
    input("   完成後，回到此終端機按下 [Enter] 鍵繼續執行...")
    print("🔔" * 20 + "\n")
    return True


# ── 軌跡錄製與播放 ────────────────────────────────────────
def record_setup_actions():
    print("=" * 58)
    print("進入【錄製模式】")
    print("請在 Chrome 中操作右側側邊欄，設定所有參數。")
    print("完成後，按下鍵盤 [Esc] 鍵結束錄製並存檔。")
    print("=" * 58)
    
    activate_chrome()
    actions = []
    last_time = time.time()

    def on_click(x, y, button, pressed):
        nonlocal last_time
        if pressed:
            win = get_chrome_window()
            if win:
                rel_x = x - win.left
                rel_y = y - win.top
                delay = time.time() - last_time
                actions.append({"type": "click", "x": rel_x, "y": rel_y, "delay": delay})
                last_time = time.time()
                print(f"錄製點擊: ({rel_x}, {rel_y}), 延遲: {delay:.2f}s")

    def on_press(key):
        if key == keyboard.Key.esc:
            print("\n結束錄製，存檔中...")
            with open(ACTIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(actions, f, indent=4)
            return False
        
        win = get_chrome_window()
        if win:
            delay = time.time() - last_time
            # pynput 的一般按鍵字串會帶有單引號 (例如 "'a'")，需要清除
            key_str = str(key).replace("Key.", "").strip("'")
            actions.append({"type": "key", "key": key_str, "delay": delay})
            last_time = time.time()
            print(f"錄製按鍵: {key_str}, 延遲: {delay:.2f}s")

    def on_scroll(x, y, dx, dy):
        nonlocal last_time
        win = get_chrome_window()
        if win:
            delay = time.time() - last_time
            # pynput 的 dy 在 Windows 上通常是 1 或 -1
            actions.append({"type": "scroll", "clicks": dy, "delay": delay})
            last_time = time.time()
            print(f"錄製滾輪: 滾動方向 {dy}, 延遲: {delay:.2f}s")

    with mouse.Listener(on_click=on_click, on_scroll=on_scroll) as m_listener, keyboard.Listener(on_press=on_press) as k_listener:
        m_listener.join()
        k_listener.join()
    
    print(f"✅ 錄製完成，已存入 {ACTIONS_FILE}")

def play_setup_actions():
    if not ACTIONS_FILE.exists():
        log.error("找不到 setup_actions.json！請先執行 --record 錄製參數設定過程。")
        sys.exit(1)
    
    with open(ACTIONS_FILE, "r", encoding="utf-8") as f:
        actions = json.load(f)
    
    log.info(f"開始播放錄製的設定動作 ({len(actions)} 個步驟)...")
    activate_chrome()
    
    for i, action in enumerate(actions):
        time.sleep(action.get("delay", 0.5))
        win = get_chrome_window()
        if not win:
            log.error("播放過程中找不到 Chrome 視窗！")
            return False
        
        if action["type"] == "click":
            abs_x = win.left + action["x"]
            abs_y = win.top + action["y"]
            pyautogui.moveTo(abs_x, abs_y, duration=0.2)
            pyautogui.click()
        elif action["type"] == "scroll":
            # PyAutoGUI 的 scroll 接受 clicks，通常在 Windows 上需要放大 (例如 *120 或 *200)
            pyautogui.scroll(int(action["clicks"] * 150))
        elif action["type"] == "key":
            key = action["key"]
            # 處理 pynput 的特殊鍵名轉換給 pyautogui
            if key == "enter": pyautogui.press("enter")
            elif key == "esc": pyautogui.press("escape")
            elif key == "down": pyautogui.press("down")
            elif key == "up": pyautogui.press("up")
            elif key == "space": pyautogui.press("space")
            elif key == "page_down": pyautogui.press("pagedown")
            elif key == "page_up": pyautogui.press("pageup")
            else:
                try:
                    pyautogui.press(key)
                except Exception as e:
                    log.warning(f"無法播放按鍵 {key}: {e}")
            
    log.info("✅ 參數設定軌跡播放完畢")
    return True


# ── 核心流程 ─────────────────────────────────────────────
def launch_chrome():
    log.info("啟動一般 Chrome (無遠端偵錯)...")
    subprocess.Popen([CHROME_PATH, f"--user-data-dir={USER_DATA_DIR}", AI_STUDIO_URL])
    time.sleep(10)
    activate_chrome()

def setup_new_chat():
    log.info("[Step 0] 開啟全新對話串...")
    activate_chrome()
    if not find_and_click("new_chat_btn", confidence=0.7, timeout=10):
        human_takeover("找不到 New chat 按鈕，請手動點擊")
    time.sleep(3)
    
    log.info("[Step 1] 播放錄製的參數設定軌跡...")
    if not play_setup_actions():
        human_takeover("參數設定播放失敗，請手動設定參數")
    time.sleep(2)

def submit_prompt(ref_text: str) -> bool:
    log.info("[送出] 準備透過純 OS 事件貼上並送出...")
    activate_chrome()
    pyperclip.copy(ref_text)
    
    if not find_and_click("input_box", confidence=0.7, timeout=10):
        human_takeover("找不到輸入框，請手動點擊輸入框")
    
    # 模擬人類按鍵節奏 (避免被 reCAPTCHA 偵測)
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
    
    log.info("[送出] ✅ 已送出 Prompt")
    return True

def wait_and_extract() -> str | None:
    log.info(f"[等待] 等待模型生成 ({WAIT_SECONDS} 秒)...")
    for remaining in range(WAIT_SECONDS, 0, -1):
        mins, secs = divmod(remaining, 60)
        sys.stdout.write(f"\r  ⏳ 剩餘: {mins:02d}:{secs:02d} ")
        sys.stdout.flush()
        time.sleep(1)
    print()
    
    log.info("[提取] 嘗試提取生成的 Markdown...")
    activate_chrome()
    
    screen_w, screen_h = pyautogui.size()
    
    # 1. 移動到畫面正中央懸停，讓選單出現
    log.info("[提取] 移動滑鼠至畫面正中央懸停...")
    pyautogui.moveTo(screen_w // 2, screen_h // 2, duration=0.5)
    time.sleep(1.5) 
    
    # 2. 尋找畫面上所有的三點按鈕
    img_path = IMAGE_DIR / "model_options_btn.png"
    if not img_path.exists():
        human_takeover("找不到 model_options_btn.png 截圖")
        time.sleep(1)
    else:
        try:
            locations = list(pyautogui.locateAllOnScreen(str(img_path), confidence=0.7))
            target_box = None
            
            # 3. 篩選出位於右側 1/3 區域的按鈕
            right_third_start = screen_w * (2 / 3)
            for loc in locations:
                center = pyautogui.center(loc)
                if center.x >= right_third_start:
                    target_box = loc
                    break
            
            if target_box:
                # target_box 是一個 Box 物件 (left, top, width, height)
                # 因為圖片包含了三個按鈕，我們要點擊最右側的那個，所以 X 座標取 left + width * (5/6)
                click_x = target_box.left + int(target_box.width * 5 / 6)
                click_y = target_box.top + int(target_box.height / 2)
                
                log.info(f"[提取] 找到右側三點按鈕群組，點擊右側 1/3 座標: ({click_x}, {click_y})")
                pyautogui.moveTo(click_x, click_y, duration=0.3)
                pyautogui.click()
                time.sleep(1)
            else:
                human_takeover("找不到位於右側 1/3 的三點按鈕，請手動點擊")
        except Exception as e:
            human_takeover(f"影像辨識發生錯誤: {e}，請手動點擊三點按鈕")
    
    # 4. 尋找 Copy as Markdown 按鈕
    if not find_and_click("copy_as_markdown", confidence=0.7, timeout=5):
        human_takeover("找不到 copy_as_markdown 按鈕，請手動點擊")
    
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', action='store_true', help="錄製參數設定軌跡")
    args = parser.parse_args()

    print("=" * 58)
    print("  Google AI Studio 全自動化腳本 (純 OS + 軌跡錄製版)")
    print("  緊急中止: 將滑鼠快速移到螢幕最左上角")
    print("=" * 58)

    launch_chrome()

    if args.record:
        record_setup_actions()
        return

    last_mtime: float = time.time()
    if REF_FILE.exists():
        # 設定為檔案當前的修改時間，確保只有在未來檔案被更新時才觸發
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
                setup_new_chat()
                time.sleep(3)

            submit_prompt(ref_text)
            md_content = wait_and_extract()

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
            log.error(f"未預期的錯誤: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()