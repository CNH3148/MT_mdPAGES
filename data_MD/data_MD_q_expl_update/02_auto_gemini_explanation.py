"""
02_auto_gemini_explanation.py — 自動化 Gemini 側邊欄生成題目詳解

透過 pyautogui 影像辨識 + human_input 擬人化操控 Chrome 內建 Gemini 對話框，
自動為 data_MD 中的考題產生「筆記與詳解」。

用法:
    uv run --with pyautogui --with pydirectinput --with pyperclip --with pygetwindow \
           --with opencv-python --with pillow \
           python 02_auto_gemini_explanation.py [--manual-send] [--start-from FILENAME] [--dry-run]
                                                [--auto-git] [--commit-interval SECONDS]
"""

import argparse
import importlib
import logging
import subprocess
import sys
import time
import traceback
import winsound
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any

# Add data_MD_update to path to import human_input
sys.path.append(str(Path(__file__).resolve().parent.parent / "data_MD_update"))
try:
    from human_input import (
        jsleep,
        human_click,
        human_hotkey,
        human_press,
        human_scroll,
    )
except ImportError as e:
    print(f"Error importing human_input: {e}")
    sys.exit(1)

import pyautogui
import pyperclip

from _utils import (
    IMAGE_DIR,
    DATA_ROOT,
    CSV_FILENAME,
    read_question_list,
    update_question_status,
    parse_frontmatter,
    parse_question_components,
    STATUS_PENDING,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_FAILED,
    logger,
)

validate_mod = importlib.import_module("03_validate")
run_validation = validate_mod.run_validation

class QuotaLimitException(Exception):
    pass

# ---------------------------------------------------------------------------
# Helper: beep alert (winsound)
# ---------------------------------------------------------------------------
def beep_alert() -> None:
    """Emit a short beep to alert the human operator."""
    try:
        winsound.Beep(1000, 500)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Git periodic commit & push
# ---------------------------------------------------------------------------
_REPO_ROOT: Path = DATA_ROOT.parent  # data_MD_PAGE/

def check_git_auth() -> None:
    """Pre-flight check to trigger GitHub login prompt if credentials are not cached.
    
    Runs a harmless `git ls-remote origin` command. If the user needs to login,
    the Git Credential Manager will pop up immediately. Wait up to 60 seconds
    for the user to complete the login.
    """
    logger.info("Checking GitHub authentication status...")
    try:
        result = subprocess.run(
            ["git", "ls-remote", "origin"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error(f"GitHub auth check failed: {result.stderr.strip()}")
            sys.exit(1)
        logger.info("GitHub auth check passed.")
    except subprocess.TimeoutExpired:
        logger.error("GitHub auth check timed out (60s). Please ensure you are logged in.")
        sys.exit(1)
    except Exception as exc:
        logger.error(f"GitHub auth check raised an exception: {exc}")
        sys.exit(1)

def git_commit_and_push(completed_count: int, failed_count: int) -> bool:
    """Stage changes under data_MD/, commit with timestamp, and push.

    Only commits the ``data_MD/`` subtree so unrelated workspace changes
    are never accidentally included.

    Returns True on success, False on any failure (failures are logged
    but **never** interrupt the main automation loop).
    """
    timestamp: str = datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_msg: str = f"auto: 02 script periodic save ({timestamp}, {completed_count} done, {failed_count} failed)"

    steps: list[tuple[str, list[str]]] = [
        ("git add", ["git", "add", "data_MD/"]),
        ("git commit", ["git", "commit", "-m", commit_msg]),
        ("git pull", ["git", "pull", "--rebase", "origin", "master"]),
        ("git push", ["git", "push", "origin", "master"]),
    ]

    for label, cmd in steps:
        try:
            result = subprocess.run(
                cmd,
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                stderr_msg: str = result.stderr.strip()
                # 'nothing to commit' is normal, not an error
                if label == "git commit" and ("nothing to commit" in result.stdout or "nothing to commit" in stderr_msg):
                    logger.info("git commit: nothing to commit. Proceeding to pull/push...")
                    continue
                    
                logger.warning(f"{label} failed (rc={result.returncode}): {stderr_msg}")
                
                # If pull --rebase fails, abort the rebase to keep local repo clean
                if label == "git pull":
                    logger.warning("git pull failed. Aborting rebase to keep local repo clean...")
                    subprocess.run(["git", "rebase", "--abort"], cwd=str(_REPO_ROOT), capture_output=True)
                    
                return False
            logger.info(f"{label} succeeded.")
        except subprocess.TimeoutExpired:
            logger.warning(f"{label} timed out (120s). Skipping remaining git steps.")
            return False
        except Exception as exc:
            logger.warning(f"{label} raised an exception: {exc}")
            return False

    logger.info(f"Git sync completed: {commit_msg}")
    return True


# ---------------------------------------------------------------------------
# locate_image — pure detection (no click)
# ---------------------------------------------------------------------------
def locate_image(
    image_names: str | list[str],
    confidence: float = 0.85,
    timeout: float = 5,
) -> Any:
    """Try to find *image_names* on screen within *timeout* seconds.
    Returns the Box or None."""
    if isinstance(image_names, str):
        image_names = [image_names]

    img_paths = []
    for name in image_names:
        img_path = IMAGE_DIR / name
        if not img_path.exists():
            raise FileNotFoundError(f"Image not found on disk: {img_path}")
        img_paths.append(img_path)

    deadline = time.time() + timeout
    while time.time() < deadline:
        for img_path in img_paths:
            try:
                loc = pyautogui.locateOnScreen(str(img_path), confidence=confidence)
                if loc:
                    return loc
            except pyautogui.ImageNotFoundException:
                pass
        jsleep(0.5, 0.8)
    return None


# ---------------------------------------------------------------------------
# click_image — detect then click
# ---------------------------------------------------------------------------
def click_image(
    image_names: str | list[str],
    confidence: float = 0.85,
    timeout: float = 10,
    click_type: str = "center",
    x_offset: int = 0,
    y_offset: int = 0,
) -> bool:
    """Locate *image_names* on screen and click it with human_click.

    click_type: 'center' | 'left_third' | 'right_end'
    Returns True if found & clicked, False otherwise.
    """
    loc = locate_image(image_names, confidence=confidence, timeout=timeout)
    if loc is None:
        return False

    x, y, w, h = loc.left, loc.top, loc.width, loc.height

    if click_type == "left_third":
        target_x = x + w // 6
    elif click_type == "right_end":
        target_x = x + w - 10
    else:  # center
        target_x = x + w // 2

    target_y = y + h // 2
    target_x += x_offset
    target_y += y_offset

    human_click(target_x, target_y)
    return True


# ===================================================================
#  Step (1) — Open side panel
# ===================================================================
def open_side_panel() -> None:
    """Alt+G to open the Gemini side panel.
    Checks if it's already open first."""
    # 防呆：避免滑鼠在角落觸發 FailSafeException
    try:
        x, y = pyautogui.position()
        w, h = pyautogui.size()
        if x <= 10 or y <= 10 or x >= w - 10 or y >= h - 10:
            logger.info("Mouse is near the corner. Moving to center to avoid FailSafeException.")
            pyautogui.moveTo(w // 2, h // 2)
    except Exception:
        pass

    if locate_image(["gemini_input_box.png", "gemini_input_box_2.png"], timeout=1) is not None:
        logger.info("Side panel is already open.")
        return
        
    for attempt in range(3):
        logger.info(f"Opening Gemini side panel (Alt+G) - Attempt {attempt+1}")
        human_hotkey("alt", "g")
        jsleep(2.0, 3.0)

        if locate_image(["gemini_input_box.png", "gemini_input_box_2.png"], timeout=3) is not None:
            return
        logger.warning("Side panel not detected — retrying Alt+G")
        
    raise RuntimeError("Could not open side panel after multiple attempts")


# ===================================================================
#  Steps (2)-(3) — New chat
# ===================================================================
def start_new_chat() -> None:
    """Click ⋮ (more_options, left-third) → move down to click new chat."""
    logger.info("Step 2: Clicking more_options (left 1/3)")
    
    loc = locate_image("gemini_more_options(need_click_left).png", timeout=5)
    if loc is None:
        raise RuntimeError("Could not find gemini_more_options")
        
    x, y, w, h = loc.left, loc.top, loc.width, loc.height
    target_x = x + w // 6
    target_y = y + h // 2
    
    human_click(target_x, target_y)
    jsleep(1.0, 1.5)

    logger.info("Step 3: Moving down and clicking new chat")
    new_chat_y = target_y + 55
    human_click(target_x, new_chat_y)
    jsleep(2.0, 3.0)

    # If the menu is still open, it means it was already a new chat and the button did nothing.
    # Close it by clicking more_options again.
    if locate_image(["gemini_new_chat.png", "already_new_chat.png"], timeout=1.5) is not None:
        logger.info("Menu still open (already a new chat) — clicking more_options again to close")
        human_click(target_x, target_y)
        jsleep(0.8, 1.2)


# ===================================================================
#  Steps (4)-(5) — Model selection + thinking toggle
# ===================================================================
def setup_model(difficulty: str) -> str:
    """Select Flash or Pro based on difficulty, then enable 延長思考.

    Returns the model name string ('flash' or 'pro').
    """
    target_model = "flash"
    if difficulty in ("適中", "困難", "非常困難"):
        target_model = "pro"

    logger.info(f"Step 4: target model={target_model} (difficulty={difficulty})")

    model_clicked = False

    for attempt in range(4):
        is_flash = False
        is_pro = False
        current_btn = None
        
        for btn, is_f, is_p in [
            ("switch_model_from_flash.png", True, False),
            ("switch_model_from_pro.png", False, True),
            ("switch_model_from_auto.png", False, False),
            ("switch_model_from_flash-lite.png", False, False),
            ("flash_thinking.png", False, False),
            ("pro_thinking.png", False, False),
            ("flash-lite_thinking.png", False, False)
        ]:
            if locate_image(btn, timeout=0.5) is not None:
                current_btn = btn
                is_flash = is_f
                is_pro = is_p
                break
                
        if not current_btn:
            logger.warning("Could not find current model button, retrying...")
            jsleep(1.0, 2.0)
            continue
            
        logger.info(f"Opening model menu to check settings (attempt {attempt+1})")
        click_image(current_btn, timeout=2)
        jsleep(1.5, 2.0)
        
        if model_clicked:
            model_correct = True
        else:
            model_correct = (is_flash and target_model == "flash") or (is_pro and target_model == "pro")
            
        thinking_on = locate_image("switch_on.png", timeout=1.5) is not None
        
        if model_correct and thinking_on:
            logger.info("Model and thinking toggle are correct. Closing menu.")
            target_opt = "gemini_pro_model.png" if target_model == "pro" else "gemini_flash_model.png"
            click_image(target_opt, timeout=2)
            jsleep(1.0, 1.5)
            return target_model
            
        logger.info(f"Settings incorrect: model_correct={model_correct}, thinking_on={thinking_on}")
        if not model_correct:
            logger.info("Switching model...")
            target_opt = "gemini_pro_model.png" if target_model == "pro" else "gemini_flash_model.png"
            click_image(target_opt, timeout=3)
            jsleep(2.0, 3.0)
            model_clicked = True
            continue
            
        if not thinking_on:
            logger.info("Enabling 延長思考...")
            click_image(
                "gemini_thinking_toggle(need_click_right_end).png",
                click_type="right_end",
                timeout=3,
                x_offset=-25,
            )
            jsleep(2.0, 3.0)
            continue

    raise RuntimeError("Failed to setup model and thinking toggle after multiple attempts.")


# ===================================================================
#  Steps (6)-(8) — Input prompt
# ===================================================================
def input_prompt(q: dict) -> None:
    """Click input box → construct prompt with skill prefix → paste question."""
    logger.info("Step 6: Clicking input box and clearing it")
    if not click_image(["gemini_input_box.png", "gemini_input_box_2.png"], timeout=5):
        raise RuntimeError("Could not find input box")
    jsleep(0.8, 1.2)
    
    # Clear any existing text (useful for retries)
    human_hotkey("ctrl", "a")
    jsleep(0.3, 0.5)
    human_press("backspace")
    jsleep(0.5, 1.0)

    logger.info("Step 7: Triggering skill via UI")
    human_press("/")
    jsleep(1.0, 1.5)
    
    if click_image("gemini_skill_item.png", timeout=3):
        logger.info("Successfully clicked skill item.")
        jsleep(0.8, 1.2)
        fallback_mode = False
    else:
        logger.warning("Could not find gemini_skill_item.png, falling back to pasting full prompt.")
        fallback_mode = True

    logger.info("Step 8: Constructing and pasting prompt")
    filepath = DATA_ROOT / q["relative_path"]
    metadata, body = parse_frontmatter(filepath)
    answer = metadata.get("answer", "")

    lines = body.splitlines()
    clean_lines = []
    for line in lines:
        s = line.strip()
        if s == "## 題目":
            continue
        if s.startswith(">"):
            continue
        if s == "---":
            continue
        if s == "## 筆記與詳解":
            break
        if s:
            clean_lines.append(s)

    q_text_clean = "\n".join(clean_lines)
    
    if fallback_mode:
        prompt_text = f"/test_explainer_1Q \n{q_text_clean}\n答案：{answer}\n \n"
    else:
        prompt_text = f"{q_text_clean}\n答案：{answer}\n \n"

    pyperclip.copy(prompt_text)
    jsleep(0.3, 0.6)
    human_hotkey("ctrl", "v")
    jsleep(1.0, 1.5)


# ===================================================================
#  Step (9) — Submit
# ===================================================================
def submit_prompt(manual_send: bool = False) -> bool:
    """Press Enter or click send button to submit the prompt.
       Returns True if skill activated successfully, False otherwise.
    """
    if manual_send:
        logger.info("Manual-send mode — please send the prompt yourself")
        beep_alert()
        deadline = time.time() + 60
        while time.time() < deadline:
            if locate_image("gemini_stop_btn.png", timeout=1) is not None:
                return True
            jsleep(1.0, 1.5)
        logger.warning("stop_btn never appeared in manual-send wait")
        return False

    logger.info("Step 9: Submitting prompt")
    if not click_image("gemini_send_btn.png", timeout=3):
        logger.info("send_btn not found — pressing Enter as fallback")
        human_press("enter")
    
    logger.info("Checking if skill was triggered successfully...")
    success = False
    deadline = time.time() + 10  # 10 seconds to verify
    while time.time() < deadline:
        has_stop = locate_image("gemini_stop_btn.png", timeout=0.5) is not None
        has_skill = locate_image("skill_activated.png", timeout=0.5) is not None
        if has_stop and has_skill:
            logger.info("Skill activation confirmed!")
            success = True
            break
        jsleep(0.5, 1.0)
        
    if success:
        return True
        
    logger.warning("Skill not activated or not generating properly.")
    
    # Click stop if it's generating something else
    if click_image("gemini_stop_btn.png", timeout=2):
        logger.info("Clicked stop button.")
        jsleep(1.5, 2.5)
        
    return False


# ===================================================================
#  Steps (10)-(12) — Wait for response, scroll, copy
# ===================================================================
def wait_and_copy(model: str) -> str:
    """Wait for generation to finish, scroll to copy button, copy text."""
    initial_wait = 20 if model == "flash" else 40
    logger.info(f"Step 10: Waiting {initial_wait}s for {model}…")
    jsleep(initial_wait, initial_wait + 5)

    # Poll until stop_btn disappears (max 3 min)
    deadline = time.time() + 180
    while time.time() < deadline:
        if locate_image("gemini_stop_btn.png", timeout=1) is None:
            logger.info("gemini_stop_btn not detected, verifying...")
            jsleep(2.0, 3.0)
            if locate_image("gemini_stop_btn.png", timeout=2) is None:
                logger.info("Confirmed gemini_stop_btn has disappeared. Generation finished.")
                break
            else:
                logger.info("gemini_stop_btn reappeared. Continuing wait...")
        jsleep(3.0, 5.0)
    jsleep(2.0, 3.0)

    logger.info("Step 11: Generation done — locating gemini_mark")
    mark_loc = locate_image("gemini_mark.png", timeout=5)
    if mark_loc is None:
        raise RuntimeError("Could not find gemini_mark")

    # Hover near the mark to focus the scrollable area without clicking
    pyautogui.moveTo(mark_loc.left + mark_loc.width + 100, mark_loc.top + 10)
    jsleep(0.5, 1.0)

    logger.info("Scrolling to find copy button")
    for _ in range(10):
        if locate_image("gemini_copy_btn.png", timeout=1) is not None:
            break
        human_scroll(-1500)
        jsleep(0.8, 1.2)
    else:
        raise RuntimeError("Could not find copy button after scrolling")

    logger.info("Scrolling down slightly to ensure quota limit is visible if present")
    human_scroll(-1500)
    jsleep(1.0, 1.5)

    if locate_image("reached_quota_limit.png", timeout=2.0) is not None:
        logger.warning("reached_quota_limit.png detected before copying.")
        raise QuotaLimitException("Quota limit reached for this generation.")

    logger.info("Step 12: Clicking copy button")
    click_image("gemini_copy_btn.png", timeout=3)
    jsleep(1.0, 1.5)

    return pyperclip.paste()


# ===================================================================
#  Step (13) — Validate & deploy
# ===================================================================
def process_question(q: dict, manual_send: bool) -> bool:
    """Full pipeline for a single question. Returns True on success."""
    csv_path = Path(__file__).resolve().parent / CSV_FILENAME

    try:
        model = setup_model(q["difficulty"])
        
        success_trigger = False
        for attempt in range(3):
            if attempt > 0:
                logger.info(f"Retrying prompt submission (Attempt {attempt+1})...")
            input_prompt(q)
            if submit_prompt(manual_send):
                success_trigger = True
                break
                
        if not success_trigger:
            raise RuntimeError("Failed to activate skill after multiple submit attempts")
            
        response = wait_and_copy(model)

        if not response or len(response.strip()) < 50:
            raise RuntimeError("Copied response is empty or too short")

        is_valid, msg = run_validation(q["relative_path"], response)

        if is_valid:
            logger.info(f"✓ Validation passed: {q['filename']}")
            update_question_status(
                csv_path, q["filename"], STATUS_COMPLETED, model_used=model
            )
            return True
        else:
            logger.error(f"✗ Validation failed for {q['filename']}: {msg}")
            update_question_status(
                csv_path, q["filename"], STATUS_FAILED, error_msg=msg
            )
            return False

    except QuotaLimitException:
        raise  # Propagate to main loop for account switching
    except Exception as e:
        logger.error(f"Error processing {q['filename']}: {e}")
        traceback.print_exc()
        update_question_status(
            csv_path, q["filename"], STATUS_FAILED, error_msg=str(e)
        )
        return False


# ===================================================================
#  Quota Limit Recovery Handlers
# ===================================================================

def parse_quota_recovery_time(text: str) -> Optional[datetime]:
    # text 範例: 必須等到 7月 8 2:36 下午 額度重設後...
    pattern = r"等到\s*(\d+)\s*月\s*(\d+)\s*(\d+):(\d+)\s*(上午|下午)"
    match = re.search(pattern, text)
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    hour = int(match.group(3))
    minute = int(match.group(4))
    ampm = match.group(5)
    
    if ampm == "下午" and hour < 12:
        hour += 12
    elif ampm == "上午" and hour == 12:
        hour = 0
        
    now = datetime.now()
    year = now.year
    
    try:
        recovery_dt = datetime(year, month, day, hour, minute)
    except ValueError:
        return None
        
    # 如果時間在過去超過一天，假設是跨年
    if recovery_dt < now - timedelta(days=1):
        try:
            recovery_dt = recovery_dt.replace(year=year + 1)
        except ValueError:
            pass
            
    return recovery_dt

def attempt_read_recovery_text() -> str:
    loc = locate_image("reached_quota_limit.png", timeout=2.0)
    if not loc:
        return ""
        
    # 確保游標在圖片左上角，再略往左上偏移一點確保框到
    x = loc.left - 10
    y = loc.top - 10
    
    pyautogui.moveTo(x, y)
    pyautogui.click() # clear previous selection
    jsleep(0.2, 0.5)
    
    pyautogui.mouseDown()
    jsleep(0.2, 0.5)
    # 向下拖曳約80px並往右拖曳，覆蓋兩行文字
    pyautogui.moveTo(x + 500, y + 80, duration=0.8)
    pyautogui.mouseUp()
    jsleep(0.5, 1.0)
    
    human_hotkey("ctrl", "c")
    jsleep(0.5, 1.0)
    
    # 點擊空白處取消選取
    pyautogui.click()
    jsleep(0.2, 0.5)
    
    return pyperclip.paste()

def wait_for_quota_recovery() -> bool:
    dt = None
    for attempt in range(2):
        text = attempt_read_recovery_text()
        logger.info(f"嘗試框選的恢復時間文字: {text.strip()}")
        dt = parse_quota_recovery_time(text)
        if dt:
            break
        logger.warning(f"第 {attempt+1} 次無法解析出時間，再試一次...")
        jsleep(1.0, 2.0)
    else:
        logger.error("經過兩次嘗試仍無法解析出恢復時間。")
        return False
        
    now = datetime.now()
    wait_time = (dt - now).total_seconds()
    if wait_time < 0:
        logger.warning("解析出的恢復時間在過去，繼續執行。")
        wait_time = 0
        
    wait_time += 300 # 加5分鐘緩衝
    
    if wait_time > 12 * 3600:
        logger.error(f"需要等待的時間太久 ({wait_time} 秒，大於 12 小時)，放棄執行。")
        return False
        
    logger.info(f"開始等待額度恢復。預計恢復時間: {dt}，等待秒數: {wait_time}")
    beep_alert()
    
    while wait_time > 0:
        sleep_chunk = min(wait_time, 300) # 每5分鐘印一次進度
        jsleep(sleep_chunk, sleep_chunk)
        wait_time -= sleep_chunk
        if wait_time > 0:
            logger.info(f"持續等待中... 剩餘約 {int(wait_time)} 秒")
            
    logger.info("等待結束，恢復任務。")
    return True


# ===================================================================
#  System Sleep Prevention
# ===================================================================
def prevent_system_sleep() -> None:
    """防止 Windows 系統進入休眠、關閉螢幕或啟動螢幕保護程式。"""
    try:
        import ctypes
        # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001) | ES_DISPLAY_REQUIRED (0x00000002)
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
        logger.info("已成功呼叫 Windows API，防止系統閒置休眠與關閉螢幕。")
    except Exception as e:
        logger.warning(f"無法設定防止系統休眠: {e}")

# ===================================================================
#  Main loop
# ===================================================================
def main() -> None:
    prevent_system_sleep()
    parser = argparse.ArgumentParser(description="Auto Gemini Explanation")
    parser.add_argument("--manual-send", action="store_true",
                        help="Wait for human to press send")
    parser.add_argument("--start-from", type=str,
                        help="Start from a specific filename")
    parser.add_argument("--dry-run", action="store_true",
                        help="Just list pending questions, don't run")
    parser.add_argument("--auto-git", action="store_true",
                        help="Enable automatic git pull/commit/push periodically.")
    parser.add_argument("--commit-interval", type=int, default=3600,
                        help="Interval in seconds between periodic git sync (default: 3600 = 1h).")
    args = parser.parse_args()

    csv_path = Path(__file__).resolve().parent / CSV_FILENAME
    rows = read_question_list(csv_path)
    pending = [r for r in rows if r["status"] in (STATUS_PENDING, STATUS_FAILED, STATUS_IN_PROGRESS)]

    if args.start_from:
        idx = next(
            (i for i, q in enumerate(pending) if q["filename"] == args.start_from),
            -1,
        )
        if idx >= 0:
            pending = pending[idx:]
        else:
            logger.error(f"--start-from {args.start_from} not found")
            return

    logger.info(f"Found {len(pending)} pending/failed questions.")

    if args.dry_run:
        for q in pending[:20]:
            print(f"  {q['filename']}  difficulty={q['difficulty']}")
        if len(pending) > 20:
            print(f"  … and {len(pending) - 20} more")
        return

    # --- Check Auth if auto git enabled ---
    if args.auto_git:
        check_git_auth()

    # --- Open panel once ---
    open_side_panel()
    jsleep(2.0, 3.0)

    chat_count = 0
    consecutive_fails = 0
    completed_count = 0
    failed_count = 0
    last_commit_time: float = time.time()
    commit_interval: int = args.commit_interval

    def handle_quota_limit() -> bool:
        logger.info("Quota limit reached ('reached_quota_limit.png' detected). Switching account...")
        icon_1 = locate_image("user_icon_1.png", timeout=2.0)
        icon_2 = locate_image("user_icon_2.png", timeout=2.0)
        
        if icon_1:
            logger.info("Found user_icon_1. Clicking it to switch to account 2.")
            click_image("user_icon_1.png", timeout=2)
            jsleep(2.0, 3.0)
            click_image("change_profile.png", timeout=3)
            jsleep(2.0, 3.0)
            click_image("user_profile_2.png", timeout=3)
            jsleep(5.0, 6.0)
            return True
        elif icon_2:
            logger.info("Found user_icon_2. Clicking it to switch to account 1.")
            click_image("user_icon_2.png", timeout=2)
            jsleep(2.0, 3.0)
            click_image("change_profile.png", timeout=3)
            jsleep(2.0, 3.0)
            click_image("user_profile_1.png", timeout=3)
            jsleep(5.0, 6.0)
            return True
        else:
            logger.critical("Could not find any user icon to switch accounts.")
            return False

    for q in pending:
        quota_hits_for_this_question = 0
        while True:
            logger.info(f"{'='*50}")
            logger.info(f"Processing: {q['filename']}  (difficulty={q['difficulty']})")
            update_question_status(csv_path, q["filename"], STATUS_IN_PROGRESS)

            # Always start a new chat for every question to avoid scrolling issues
            try:
                start_new_chat()
            except Exception as e:
                logger.error(f"Failed to start new chat: {e}")
                # Recovery: Alt+G ×2
                open_side_panel()
                jsleep(1.0, 2.0)
                try:
                    start_new_chat()
                except Exception:
                    logger.critical("Cannot recover new-chat flow. Halting.")
                    beep_alert()
                    sys.exit(1)

            try:
                success = process_question(q, manual_send=args.manual_send)
            except QuotaLimitException:
                quota_hits_for_this_question += 1
                if quota_hits_for_this_question >= 2:
                    logger.warning("Hit quota limit twice for the same question. Attempting to parse recovery time...")
                    if not wait_for_quota_recovery():
                        logger.critical("Failed to recover or wait too long. Halting.")
                        ts = time.strftime("%Y-%m-%d %H:%M:%S")
                        update_question_status(csv_path, q["filename"], STATUS_FAILED, error_msg=f"Quota Limit Reached Twice at {ts}")
                        beep_alert()
                        sys.exit(1)
                    
                    logger.info("Wait completed. Re-opening side panel to resume...")
                    open_side_panel()
                    jsleep(2.0, 3.0)
                    quota_hits_for_this_question = 0
                    continue
                
                logger.info("Quota limit reached. Switching account and retrying this question...")
                if not handle_quota_limit():
                    beep_alert()
                    sys.exit(1)
                continue  # Retry this question
            
            if success:
                consecutive_fails = 0
                completed_count += 1
                logger.info("Cooldown 5s...")
                jsleep(5.0, 5.0)
            else:
                consecutive_fails += 1
                failed_count += 1
                if consecutive_fails >= 3:
                    logger.critical("3 consecutive failures — halting.")
                    if args.auto_git:
                        logger.info("Performing final git commit before exit...")
                        git_commit_and_push(completed_count, failed_count)
                    beep_alert()
                    sys.exit(1)
                logger.warning(f"Fail #{consecutive_fails}. Attempting recovery…")
                # Recovery: reopen side panel
                open_side_panel()
                jsleep(2.0, 3.0)

            # --- Periodic git commit & panel reset (regardless of success/fail) ---
            if (time.time() - last_commit_time) >= commit_interval:
                if args.auto_git:
                    logger.info(f"定時 commit 觸發（已超過 {commit_interval} 秒）...")
                    git_commit_and_push(completed_count, failed_count)
                
                logger.info("定期重開側邊欄，確保懸浮視窗回到右上角初始位置...")
                try:
                    x, y = pyautogui.position()
                    w, h = pyautogui.size()
                    if x <= 10 or y <= 10 or x >= w - 10 or y >= h - 10:
                        pyautogui.moveTo(w // 2, h // 2)
                except Exception:
                    pass
                
                human_hotkey("alt", "g")  # 關閉側邊欄
                jsleep(2.0, 3.0)
                open_side_panel()         # 重新開啟（內含防呆）
                
                last_commit_time = time.time()

            break  # Move to next question in pending

    # --- Final commit after all questions processed ---
    if args.auto_git:
        logger.info("All questions processed. Performing final git commit...")
        git_commit_and_push(completed_count, failed_count)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("使用者強制中止程式 (KeyboardInterrupt)，安全退出。")
        sys.exit(0)
