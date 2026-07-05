"""
06-4_GLM-5.2_edited_auto_chrome.py — Google AI Studio 全自動化腳本
=============================================================
擬人化輸入版（針對 reCAPTCHA Enterprise 事件指紋偵測修復）

== 與 06-3 的關鍵差異 ==
06-3 已正確地拔除 CDP 連線（必要條件），但仍 100% 被擋，因為
reCAPTCHA Enterprise 在「事件物理特徵」層級偵測到腳本。本版修復
四個非人類訊號：

  1. click dwell：06-3 用 pyautogui.click() dwell≈0ms → 本版 human_click dwell 50-150ms
  2. 時序熵：06-3 全固定 time.sleep → 本版全部 jsleep(min,max)
  3. 滑鼠軌跡：06-3 直線等速 → 本版貝茲曲線+鐘形速度+tremor+偶爾過衝
  4. 點擊位置：06-3 精確幾何中心 → 本版高斯散射

底層引擎改用 pydirectinput (SendInput API)，事件品質優於 pyautogui 的
mouse_event/keybd_event。

== 環境清理 ==
  - USER_DATA_DIR 改全新目錄，從未以 --remote-debugging-port 啟動過
  - 刪除 check_submit_success 死碼（避免日後誤連 CDP）
  - 啟動前偵測既有 AI Studio 視窗，避免 attach 到舊 debug Chrome process

== 半自動備援 ==
  --manual-send 旗標：腳本 setup + 複製 prompt → 嗶聲 → 你 Ctrl+V+Enter
  → 腳本接手等待/提取/部署。已證實人類送出 100% 成功的確定性逃生口。

使用方式：
  全自動：
    uv run --with pydirectinput --with pyautogui --with pyperclip \\
           --with pygetwindow --with opencv-python --with pillow \\
           python data_MD_update/06-4_GLM-5.2_edited_auto_chrome.py

  半自動（你負責最後送出）：
    ... 06-4_GLM-5.2_edited_auto_chrome.py --manual-send

緊急中止：將滑鼠快速移到螢幕最左上角（pyautogui FAILSAFE）
"""
import sys
import time
import random
import logging
import argparse
import winsound
import subprocess
from pathlib import Path

try:
    import pyautogui          # 影像辨識仍需 pyautogui
    import pyperclip
    import pygetwindow as gw
    import pydirectinput       # 顯式宣告依賴
except ImportError:
    print("請使用: uv run --with pydirectinput --with pyautogui --with pyperclip "
          "--with pygetwindow --with opencv-python --with pillow "
          "python data_MD_update/06-4_GLM-5.2_edited_auto_chrome.py")
    sys.exit(1)

# 載入擬人化輸入模組（同目錄）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import human_input as hi
from human_input import (
    jsleep, human_move_to, human_click, human_click_image,
    human_press, human_hotkey, human_scroll,
)

# ── 設定 ──────────────────────────────────────────────────
DATA_ROOT = Path("C:/Users/star0/Desktop/data_MD/data_MD_update")
REF_FILE = DATA_ROOT / "reference_for_ai.txt"
DUMPS_DIR = DATA_ROOT / "new_MD" / "dumps"
IMAGE_DIR = DATA_ROOT / "images"

DUMPS_DIR.mkdir(parents=True, exist_ok=True)

WAIT_SECONDS = 120          # 模型生成等待
POLL_INTERVAL = 2           # 監聽 reference_for_ai.txt 的間隔
SUBMIT_CHECK_DELAY = 8      # 送出後多久檢查是否被擋
MAX_AUTO_FAILURES = 3       # 連續失敗幾次後自動切半自動
TOPIC_COOLDOWN = (20, 45)   # 每題之間隨機冷卻
BLOCKED_COOLDOWN = (60, 90) # 被擋後長冷卻（避免信譽越打越爛）

CHROME_PATH = r"C:\Users\star0\AppData\Local\Google\Chrome\Application\chrome.exe"
# ★ 全新 profile 目錄，從未以 --remote-debugging-port 啟動過，排除 CDP 殘留
USER_DATA_DIR = r"C:\ChromeAutoSession"
AI_STUDIO_URL = "https://aistudio.google.com/prompts/new_chat"

# 影像辨識仍用 pyautogui，但關掉它的全域 PAUSE（節奏由 human_input 控制）
pyautogui.PAUSE = 0
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
                jsleep(1.5, 3.0)  # 確保寫入完成（jittered）
                return current_mtime
        jsleep(POLL_INTERVAL, POLL_INTERVAL + 1.5)


def get_chrome_window():
    windows = [w for w in gw.getAllWindows()
               if 'Google AI Studio' in w.title or 'Chrome' in w.title]
    return windows[0] if windows else None


def activate_chrome():
    win = get_chrome_window()
    if win:
        try:
            if win.isMinimized:
                win.restore()
            win.activate()
        except Exception as e:
            if "Error code from Windows: 0" not in str(e):
                log.warning(f"視窗啟動警告 (不影響執行): {e}")
        jsleep(0.4, 0.9)
    else:
        log.warning("找不到 Chrome 視窗！")


def find_and_click(img_name, confidence=0.8, timeout=5):
    """影像辨識定位 → human_click（不用 pyautogui.click）。"""
    img_path = IMAGE_DIR / f"{img_name}.png"
    if not img_path.exists():
        log.warning(f"缺少截圖: {img_path}")
        return False
    return human_click_image(str(img_path), confidence=confidence, timeout=timeout)


def find_and_click_right_edge(img_name, confidence=0.8, timeout=3):
    """尋找按鈕並點擊最右側 1/3 處（用於開關按鈕）。"""
    img_path = IMAGE_DIR / f"{img_name}.png"
    if not img_path.exists():
        log.warning(f"缺少截圖: {img_path}")
        return False

    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            box = pyautogui.locateOnScreen(str(img_path), confidence=confidence)
            if box:
                click_x = box.left + int(box.width * 0.85)
                click_y = box.top + int(box.height / 2)
                human_click(click_x, click_y)
                return True
        except pyautogui.ImageNotFoundException:
            pass
        except Exception:
            pass
        jsleep(0.7, 1.3)
    return False


def check_image_exists(img_name, confidence=0.8, timeout=3):
    img_path = IMAGE_DIR / f"{img_name}.png"
    if not img_path.exists():
        return False
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            if pyautogui.locateOnScreen(str(img_path), confidence=confidence):
                return True
        except Exception:
            pass
        jsleep(0.4, 0.8)
    return False


def scroll_and_find(img_name, confidence=0.8, max_scrolls=5):
    """在右側側邊欄向下滾動並尋找目標按鈕（用 human_scroll）。"""
    screen_w, screen_h = pyautogui.size()
    sidebar_x = int(screen_w * 0.8)
    sidebar_y = int(screen_h * 0.5)
    human_move_to(sidebar_x, sidebar_y)
    jsleep(0.2, 0.4)

    for attempt in range(max_scrolls + 1):
        if find_and_click(img_name, confidence=confidence, timeout=1):
            return True
        if attempt < max_scrolls:
            log.info(f"找不到 {img_name}，向下滾動側邊欄 (第 {attempt+1} 次)...")
            # 恢復足夠的滾動量 (-500)
            human_scroll(-500, smooth=True)
            jsleep(0.8, 1.3)
    return False


def beep_alert(times: int = 3):
    for _ in range(times):
        winsound.Beep(1000, 400)
        jsleep(0.2, 0.3)


def human_takeover(reason: str):
    log.error(f"❌ 自動化失敗: {reason}")
    beep_alert(3)
    print("\n" + "🔔" * 20)
    print(f"👉 [需要手動介入] {reason}")
    input("   完成後，回到此終端機按下 [Enter] 鍵繼續執行...")
    print("🔔" * 20 + "\n")


# ── 啟動 Chrome（避免 attach 舊 debug process）────────────
def launch_chrome_if_needed():
    """若 AI Studio 視窗已開則只 activate；否則才啟動新 process。

    避免把請求轉給可能仍在執行、帶有 9222 debug port 的舊 Chrome。
    """
    if get_chrome_window() is not None:
        log.info("偵測到既有的 Chrome/AI Studio 視窗，直接使用（不啟動新 process）。")
        activate_chrome()
        return
    log.info(f"啟動 Chrome（全新 profile: {USER_DATA_DIR}）...")
    subprocess.Popen([
        CHROME_PATH,
        f"--user-data-dir={USER_DATA_DIR}",
        AI_STUDIO_URL,
    ])
    jsleep(10, 13)
    activate_chrome()


# ── OS 核心流程（設定）──────────────────────────────────
def setup_new_chat_os():
    log.info("[Step 0] 重新整理網頁...")
    activate_chrome()
    human_press('f5')
    jsleep(7, 10)

    log.info("[Step 0] 開啟全新對話串...")
    if not find_and_click("new_chat_btn", confidence=0.7, timeout=10):
        raise Exception("找不到 New chat 按鈕")
    jsleep(2.5, 4.0)

    log.info("[Step 1] 設定 System Instructions...")
    if not find_and_click("sys_instruction_btn", timeout=5):
        raise Exception("找不到 System instructions 按鈕")

    if find_and_click("sys_dropdown", timeout=3):
        if not find_and_click("topic_preset", timeout=3):
            raise Exception("找不到 'topic分析撰寫指引' 選項")
        jsleep(0.8, 1.5)
        if not find_and_click("sys_close_btn", timeout=3):
            log.warning("找不到關閉按鈕 (叉叉)，嘗試按 Escape 關閉")
            human_press('escape')
        jsleep(0.8, 1.5)
    else:
        log.info("[Step 1] 找不到下拉選單，可能已預設套用 preset")
    jsleep(0.8, 1.5)

    log.info("[Step 2] 設定 Media resolution...")
    if scroll_and_find("media_resolution_btn", confidence=0.7):
        if not find_and_click("media_high_option", timeout=3):
            raise Exception("找不到 Media High 選項")
        human_press('escape')
    else:
        raise Exception("捲動到底仍找不到 Media resolution 按鈕")
    jsleep(0.8, 1.5)

    log.info("[Step 3] 設定 URL context...")
    if scroll_and_find("url_context_off", confidence=0.7):
        log.info("URL context 目前為關閉，點擊右側開啟...")
        find_and_click_right_edge("url_context_off", timeout=2)
    elif check_image_exists("url_context_on", confidence=0.7):
        log.info("✅ URL context 已經是開啟狀態")
    else:
        raise Exception("找不到 URL context 按鈕")
    jsleep(0.8, 1.5)

    log.info("✅ 側邊欄參數設定流程完畢")


# ── 送出 prompt（擬人化）────────────────────────────────
def submit_prompt_os(ref_text: str, manual_send: bool = False) -> str:
    """送出 prompt。

    manual_send=False：全自動貼上 + 點 Run。
    manual_send=True：貼上到剪貼簿後暫停，由人類送出（確定性逃生口）。

    回傳 'sent' | 'manual' | 'blocked'。
    """
    log.info("[送出] 準備透過擬人化 OS 事件貼上並送出...")
    activate_chrome()
    pyperclip.copy(ref_text)
    jsleep(0.3, 0.7)

    if not find_and_click("input_box", confidence=0.7, timeout=10):
        raise Exception("找不到輸入框")

    # ★ 移除 06-3 對空框的無意義 Ctrl+A → Delete（典型自動化特徵）
    # new_chat 的輸入框本來就是空的，不需要清空

    # 貼上（擬人化組合鍵，dwell 與間隔都 jittered）
    human_hotkey('ctrl', 'v')
    jsleep(1.8, 3.0)

    if manual_send:
        beep_alert(3)
        print("\n" + "🔔" * 20)
        print("👉 [半自動模式] prompt 已複製到剪貼簿並貼入輸入框。")
        print("👉 請在 Chrome 視窗「親自點擊 Run 按鈕」送出（已證實 100% 成功）。")
        print("   （若輸入框是空的，按 Ctrl+V 重新貼上再送出）")
        input("   送出成功、模型開始生成後，回到此終端機按 [Enter] 接手...")
        print("🔔" * 20 + "\n")
        return 'manual'

    # 全自動：擬人化點擊 Run（強化 dwell 與散射）
    if not find_and_click("run_btn", confidence=0.8, timeout=10):
        log.warning("找不到 Run 按鈕，嘗試 Ctrl+Enter...")
        human_hotkey('ctrl', 'enter')

    log.info("[送出] ✅ 已送出 Prompt (擬人化事件)")
    return 'sent'


# ── 智慧錯誤偵測（純 OS 影像，不連 CDP）─────────────────
def check_submit_status_by_image() -> str:
    """送出後短暫等待，用影像判斷送出結果。

    需要 stop_btn.png（生成中的停止按鈕）。若該截圖不存在則降級為
    「檢查 Run 按鈕是否還在」的啟發式判斷。

    回傳 'generating' | 'likely_blocked' | 'unknown'
    """
    jsleep(SUBMIT_CHECK_DELAY, SUBMIT_CHECK_DELAY + 2)
    activate_chrome()

    # 方法 A：若提供 stop_btn.png，看到它代表生成中 = 成功
    if (IMAGE_DIR / "stop_btn.png").exists():
        if check_image_exists("stop_btn", confidence=0.7, timeout=3):
            log.info("[驗證] ✅ 偵測到生成中指示，送出成功")
            return 'generating'
        # 沒看到 stop，再看 Run 是否還在 → 大機率被擋
        if check_image_exists("run_btn", confidence=0.8, timeout=2):
            log.error("[驗證] ❌ Run 按鈕仍在且無生成指示，大機率被擋")
            return 'likely_blocked'
        return 'unknown'

    # 降級：沒有 stop_btn.png，用 Run 按鈕啟發式判斷
    log.info("[驗證] 無 stop_btn.png，採啟發式判斷（Run 按鈕是否還在）...")
    if check_image_exists("run_btn", confidence=0.8, timeout=2):
        # Run 還在通常代表沒送出去（被擋）
        log.warning("[驗證] ⚠️ Run 按鈕仍在，可能被擋（建議截 stop_btn.png 提升準確度）")
        return 'likely_blocked'
    log.info("[驗證] ✅ Run 按鈕已消失，推測正在生成")
    return 'generating'


# ── 提取流程（純 OS 影像辨識）─────────────────────────────
def wait_and_extract_os() -> str | None:
    log.info(f"[等待] 等待模型生成 ({WAIT_SECONDS} 秒)...")
    for remaining in range(WAIT_SECONDS, 0, -1):
        mins, secs = divmod(remaining, 60)
        sys.stdout.write(f"\r  ⏳ 剩餘: {mins:02d}:{secs:02d} ")
        sys.stdout.flush()
        jsleep(1)
    print()

    log.info("[提取] 嘗試透過 OS 影像辨識提取生成的 Markdown...")
    activate_chrome()
    screen_w, screen_h = pyautogui.size()

    log.info("[提取] 移動滑鼠至畫面正中央懸停...")
    human_move_to(screen_w // 2, screen_h // 2)
    jsleep(1.2, 2.0)

    img_path = IMAGE_DIR / "model_options_btn.png"
    if not img_path.exists():
        raise Exception("找不到 model_options_btn.png 截圖")

    log.info("[提取] 掃描畫面上的三點按鈕...")
    boxes = list(pyautogui.locateAllOnScreen(str(img_path), confidence=0.7))
    if not boxes:
        raise Exception("畫面上找不到任何三點按鈕")

    # Y 座標最大的 = 最底部/最後一個模型回覆
    target_box = max(boxes, key=lambda b: b.top)
    # 圖片包含三個按鈕，點擊最右側那個
    click_x = target_box.left + int(target_box.width * 5 / 6)
    click_y = target_box.top + int(target_box.height / 2)
    log.info(f"[提取] 點擊最後一個三點按鈕群組右側: ({click_x}, {click_y})")
    human_click(click_x, click_y)
    jsleep(0.8, 1.4)

    if not find_and_click("copy_as_markdown", confidence=0.7, timeout=5):
        raise Exception("找不到 copy_as_markdown 按鈕")
    jsleep(0.8, 1.4)

    md_text = pyperclip.paste()
    if md_text and len(md_text) > 100:
        log.info(f"[提取] ✅ 成功！(長度: {len(md_text)})")
        md_text = md_text.replace("\r", "").replace("\n\n", "\n")
        start_idx = md_text.find("---")
        if start_idx != -1:
            md_text = md_text[start_idx:]
        md_text = md_text.strip()
        # "Copy as Markdown" 有時會在整個回應外包一層 code fence，
        # 表現為第一行是 ```markdown 或 ```，最後一行也是 ```。
        # 但我們不能盲目刪除結尾的 ```，因為它可能是 Anki 區塊的合法閉合。
        # 策略：只有當「第一行」也是 ``` 開頭時（表示存在外層 wrapper），
        # 才同時去掉首尾的 wrapper fence。
        lines = md_text.split("\n")
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
            md_text = "\n".join(lines[1:-1]).strip()
        return md_text

    log.error("[提取] ❌ 剪貼簿內容為空或太短")
    return None


# ── 主程式 ────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manual-send', action='store_true',
                        help="半自動模式：腳本 setup+貼上 prompt，由人類點 Run 送出")
    args = parser.parse_args()

    print("=" * 58)
    print("  Google AI Studio (擬人化輸入版 06-4)")
    mode_label = "半自動 (--manual-send)" if args.manual_send else "全自動"
    print(f"  模式: {mode_label}")
    print(f"  輸入引擎: {hi.ENGINE}")
    print("  緊急中止: 將滑鼠快速移到螢幕最左上角")
    print("=" * 58)

    launch_chrome_if_needed()

    last_mtime: float = time.time()
    if REF_FILE.exists():
        last_mtime = REF_FILE.stat().st_mtime

    consecutive_failures = 0
    forced_manual = args.manual_send

    while True:
        try:
            current_mtime = wait_for_new_reference(last_mtime)
            with open(REF_FILE, "r", encoding="utf-8", newline="") as f:
                ref_text = f.read()
            ref_text = ref_text.replace('\r\n', '\n').replace('\n', '\r\n')

            topic_name = extract_topic_name(ref_text)
            is_fix_prompt = ref_text.startswith("[FIX_PROMPT]")

            log.info(f"{'='*58}")
            log.info(f">>> 開始處理 Topic: {topic_name}"
                     f"{('  [FIX_PROMPT]' if is_fix_prompt else '')}")
            log.info(f"{'='*58}")

            # ---- setup（只有非 FIX_PROMPT 才需要開新 chat）-----
            if not is_fix_prompt:
                setup_ok = False
                for attempt in range(1, 4):
                    try:
                        setup_new_chat_os()
                        jsleep(2.5, 4.0)
                        setup_ok = True
                        break
                    except Exception as e:
                        if attempt < 3:
                            log.warning(f"❌ 第 {attempt} 次 setup 失敗: {e}，5 秒後重試...")
                            jsleep(4, 7)
                        else:
                            human_takeover(f"setup 失敗已達 3 次: {e}")
                            setup_ok = True  # 人類接手後視為完成
                if not setup_ok:
                    raise Exception("setup 未完成")

            # ---- 送出 ----
            send_result = submit_prompt_os(ref_text, manual_send=forced_manual)

            if send_result == 'manual':
                # 半自動：人類已送出，直接進提取
                consecutive_failures = 0
            else:
                # 全自動：用影像判斷是否被擋
                status = check_submit_status_by_image()
                if status == 'likely_blocked':
                    consecutive_failures += 1
                    log.error(f"[驗證] ❌ 疑似被擋 "
                              f"(連續 {consecutive_failures}/{MAX_AUTO_FAILURES})")
                    if consecutive_failures >= MAX_AUTO_FAILURES and not forced_manual:
                        log.warning("🔔 連續失敗達上限，自動切換為半自動模式。")
                        forced_manual = True
                        beep_alert(5)
                        print("\n" + "🔔" * 25)
                        print("👉 全自動持續被擋，已切換【半自動模式】。")
                        print("👉 本題請由你親自送出；後續每題都會先暫停等你。")
                        print("👉 （若想回全自動，重啟腳本並移除 --manual-send）")
                        print("🔔" * 25 + "\n")
                    # 長冷卻，避免信譽越打越爛
                    cd = random.uniform(*BLOCKED_COOLDOWN)
                    log.info(f"[冷卻] 被擋後等待 {cd:.0f}s 再重試...")
                    jsleep(cd, cd + 5)
                    continue  # 下一輪重送同一個 prompt（last_mtime 未更新）
                else:
                    consecutive_failures = 0

            # ---- 提取 ----
            md_content = wait_and_extract_os()

            if md_content:
                out_file = DUMPS_DIR / f"{topic_name}.md"
                out_file.write_text(md_content, encoding="utf-8")
                log.info(f"✅ 已存檔: {out_file}")
                last_mtime = current_mtime
                # 題間冷卻
                cd = random.uniform(*TOPIC_COOLDOWN)
                log.info(f"[冷卻] 題間等待 {cd:.0f}s...")
                jsleep(cd, cd + 5)
            else:
                log.error("❌ 無法取得內容，15-25 秒後重試...")
                jsleep(15, 25)

        except KeyboardInterrupt:
            log.info("收到中止訊號，安全退出。")
            break
        except Exception as e:
            if "手動介入" not in str(e):
                log.error(f"未預期的錯誤: {e}")
            jsleep(4, 7)


if __name__ == "__main__":
    main()
