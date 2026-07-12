"""
06-1_GLM-5.2_edited_auto_chrome.py — Google AI Studio 全自動化腳本 (純 OS 自動化版)

功能：
  1. 監聽 reference_for_ai.txt 的更新
  2. 啟動一般 Chrome (無 CDP 遠端偵錯)
  3. 透過影像辨識(pyautogui)自動開啟新對話
  4. 貼上 Prompt 並點擊送出
  5. 等待模型生成完畢後，透過 Copy as Markdown 提取內容
  6. 將結果存入 dumps/ 資料夾

依賴：
  uv run --with pyautogui --with pyperclip --with pygetwindow --with opencv-python --with pillow python data_MD_update/06_auto_chrome.py
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
except ImportError:
    print("請使用: uv run --with pyautogui --with pyperclip --with pygetwindow --with opencv-python --with pillow python data_MD_update/06_auto_chrome.py")
    sys.exit(1)

# ── 設定 ──────────────────────────────────────────────────
DATA_ROOT = Path("C:/Users/star0/Desktop/data_MD/data_MD_update")
REF_FILE = DATA_ROOT / "reference_for_ai.txt"
DUMPS_DIR = DATA_ROOT / "new_MD" / "dumps"
IMAGE_DIR = DATA_ROOT / "images"  # 截圖資料夾

DUMPS_DIR.mkdir(parents=True, exist_ok=True)

WAIT_SECONDS = 120  # 等待模型生成的秒數
POLL_INTERVAL = 2   # 監聽 reference_for_ai.txt 的間隔秒數

# Chrome 路與設定
CHROME_PATH = r"C:\Users\star0\AppData\Local\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = r"C:\ChromeDevSession"
AI_STUDIO_URL = "https://aistudio.google.com/prompts/new_chat"

# ── PyAutoGUI 安全設定 ────────────────────────────────────
pyautogui.PAUSE = 0.5  # 每個動作間隔 0.5 秒，更像人類
pyautogui.FAILSAFE = True  # 滑鼠移到螢幕最左上角可緊急中止

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


def activate_chrome():
    """將 Chrome 視窗帶到最上層。"""
    windows = [w for w in gw.getAllWindows() if 'Google AI Studio' in w.title or 'Chrome' in w.title]
    if windows:
        win = windows[0]
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(1)
    else:
        log.warning("找不到 Chrome 視窗！")


def find_and_click(img_name, confidence=0.8, timeout=15):
    """在螢幕上尋找指定截圖並點擊中心點。"""
    img_path = IMAGE_DIR / f"{img_name}.png"
    if not img_path.exists():
        log.error(f"找不到截圖檔案: {img_path}")
        return False

    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            location = pyautogui.locateCenterOnScreen(str(img_path), confidence=confidence)
            if location:
                # 模擬人類移動軌跡
                pyautogui.moveTo(location.x, location.y, duration=0.4)
                time.sleep(0.2)
                pyautogui.click()
                return True
        except pyautogui.ImageNotFoundException:
            pass
        except Exception as e:
            log.warning(f"影像辨識異常: {e}")
        time.sleep(1)
    
    log.warning(f"在畫面上找不到 {img_name}.png (等待 {timeout} 秒超時)")
    return False


def find_and_click_last(img_name, confidence=0.8, timeout=10):
    """尋找畫面上最後一個(最下方)符合的截圖並點擊。用於多個回覆的情況。"""
    img_path = IMAGE_DIR / f"{img_name}.png"
    if not img_path.exists():
        log.error(f"找不到截圖檔案: {img_path}")
        return False

    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            locations = list(pyautogui.locateAllOnScreen(str(img_path), confidence=confidence))
            if locations:
                # 取得 y 座標最大的那個（也就是畫面最下方的按鈕）
                last_loc = max(locations, key=lambda loc: loc.top)
                center = pyautogui.center(last_loc)
                pyautogui.moveTo(center.x, center.y, duration=0.4)
                time.sleep(0.2)
                pyautogui.click()
                return True
        except pyautogui.ImageNotFoundException:
            pass
        time.sleep(1)
    return False


def human_takeover(reason: str) -> bool:
    """自動化失敗時，發出聲音並等待人類介入。"""
    log.error(f"❌ 自動化失敗: {reason}")
    winsound.Beep(1000, 500)
    print("\n" + "🔔" * 20)
    print(f"👉 [需要手動介入] {reason}")
    print("👉 請回到 Chrome 視窗「親自」完成此步驟！")
    input("   完成後，回到此終端機按下 [Enter] 鍵繼續執行...")
    print("🔔" * 20 + "\n")
    return True


# ── 核心自動化流程 ────────────────────────────────────────
def launch_chrome():
    """啟動不帶 CDP 參數的一般 Chrome。"""
    log.info("啟動一般 Chrome (無遠端偵錯)...")
    subprocess.Popen([
        CHROME_PATH,
        f"--user-data-dir={USER_DATA_DIR}",
        AI_STUDIO_URL
    ])
    log.info("等待 Chrome 啟動與頁面載入 (15秒)...")
    time.sleep(15)
    activate_chrome()


def setup_new_chat():
    """點擊 New chat 按鈕。"""
    log.info("[Step 0] 開啟全新對話串...")
    activate_chrome()
    
    if not find_and_click("new_chat_btn", confidence=0.7, timeout=10):
        # 如果找不到按鈕，可能是頁面卡住，嘗試用快捷鍵或人工
        human_takeover("找不到 New chat 按鈕，請手動點擊 New chat")
    
    time.sleep(3)
    log.info("[Step 0] ✅ 已開啟新對話")
    
    # 注意：因為 AI Studio 會記住上一次的 System Instruction 與設定
    # 如果你的預設環境已經設定好，這裡不需要每次重新設定
    # 如果需要重新設定，請手動操作一次，Google 通常會記住狀態
    log.info("[Step 1] (略過) System Instructions 與模型設定預設沿用上次狀態")


def submit_prompt(ref_text: str) -> bool:
    """將 Prompt 貼入對話框並送出。"""
    log.info("[送出] 準備透過純 OS 事件貼上並送出...")
    activate_chrome()
    
    pyperclip.copy(ref_text)
    time.sleep(0.5)
    
    # 1. 點擊輸入框
    if not find_and_click("input_box", confidence=0.7, timeout=10):
        human_takeover("找不到輸入框，請手動點擊輸入框")
    
    # 2. 全選並刪除舊內容
    pyautogui.keyDown('ctrl')
    time.sleep(0.1)
    pyautogui.press('a')
    time.sleep(0.1)
    pyautogui.keyUp('ctrl')
    time.sleep(0.3)
    pyautogui.press('delete')
    time.sleep(0.5)
    
    # 3. 貼上新 Prompt
    pyautogui.keyDown('ctrl')
    time.sleep(0.1)
    pyautogui.press('v')
    time.sleep(0.1)
    pyautogui.keyUp('ctrl')
    time.sleep(2)
    
    # 4. 點擊 Run 按鈕
    if not find_and_click("run_btn", confidence=0.8, timeout=10):
        # 退回使用 Ctrl+Enter
        log.warning("找不到 Run 按鈕圖片，嘗試使用 Ctrl+Enter...")
        pyautogui.keyDown('ctrl')
        time.sleep(0.1)
        pyautogui.press('enter')
        time.sleep(0.1)
        pyautogui.keyUp('ctrl')
    
    log.info("[送出] ✅ 已送出 Prompt，等待模型生成...")
    return True


def wait_and_extract() -> str | None:
    """等待生成完畢，並透過 Copy as Markdown 提取結果。"""
    log.info(f"[等待] 等待模型生成 ({WAIT_SECONDS} 秒)...")
    for remaining in range(WAIT_SECONDS, 0, -1):
        mins, secs = divmod(remaining, 60)
        sys.stdout.write(f"\r  ⏳ 剩餘: {mins:02d}:{secs:02d} ")
        sys.stdout.flush()
        time.sleep(1)
    print()
    
    log.info("[提取] 嘗試提取生成的 Markdown...")
    activate_chrome()
    
    # 1. 點擊模型回覆的三點選單 (找畫面上最下方的那個)
    if not find_and_click_last("model_options_btn", confidence=0.7, timeout=10):
        human_takeover("找不到模型回覆的三點選單，請手動點擊它")
    
    time.sleep(1)
    
    # 2. 點擊 Copy as Markdown
    if not find_and_click("copy_as_markdown", confidence=0.7, timeout=5):
        # 可能選單捲動了，嘗試按 Escape 並退回 DOM 複製法 (但純OS無法用DOM)
        human_takeover("找不到 Copy as Markdown 選項，請手動點擊 Copy as Markdown")
    
    time.sleep(1)
    
    # 3. 從剪貼簿讀取
    md_text = pyperclip.paste()
    if md_text and len(md_text) > 100:
        log.info(f"[提取] ✅ 成功！(長度: {len(md_text)})")
        md_text = md_text.replace("\r", "")
        md_text = md_text.replace("\n\n", "\n")
        
        start_idx = md_text.find("---")
        if start_idx != -1:
            md_text = md_text[start_idx:]
        
        md_text = md_text.strip()
        if md_text.endswith("```"):
            md_text = md_text[:-3].strip()
            
        return md_text
    
    log.error("[提取] ❌ 剪貼簿內容為空或太短")
    return None


# ── 主迴圈 ────────────────────────────────────────────────
def main():
    print("=" * 58)
    print("  Google AI Studio 全自動化腳本 (純 OS 自動化版)")
    print("  緊急中止: 將滑鼠快速移到螢幕最左上角")
    print("=" * 58)

    # 第一次啟動 Chrome
    launch_chrome()

    last_mtime: float = 0
    if REF_FILE.exists():
        last_mtime = REF_FILE.stat().st_mtime - 10

    while True:
        try:
            current_mtime = wait_for_new_reference(last_mtime)
            
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

            if not is_fix_prompt:
                setup_new_chat()
                time.sleep(3)

            submit_prompt(ref_text)

            md_content = wait_and_extract()

            if md_content:
                out_file = DUMPS_DIR / f"{topic_name}.md"
                out_file.write_text(md_content, encoding="utf-8")
                log.info(f"✅ 已存檔: {out_file}")
                log.info(f"檔案大小: {len(md_content)} 字元")
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