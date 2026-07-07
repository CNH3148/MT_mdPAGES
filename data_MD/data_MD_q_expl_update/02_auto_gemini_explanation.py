"""
02_auto_gemini_explanation.py — 自動化 Gemini 側邊欄生成題目詳解

透過 pyautogui 影像辨識 + human_input 擬人化操控 Chrome 內建 Gemini 對話框，
自動為 data_MD 中的考題產生「筆記與詳解」。

用法:
    uv run --with pyautogui --with pydirectinput --with pyperclip --with pygetwindow \
           --with opencv-python --with pillow \
           python 02_auto_gemini_explanation.py [--manual-send] [--start-from FILENAME] [--dry-run]
"""

import argparse
import importlib
import logging
import sys
import time
import traceback
import winsound
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

    for attempt in range(4):
        is_flash = locate_image("switch_model_from_flash.png", timeout=1.5) is not None
        is_pro = locate_image("switch_model_from_pro.png", timeout=1.5) is not None
        
        current_btn = "switch_model_from_flash.png" if is_flash else "switch_model_from_pro.png"
        if not is_flash and not is_pro:
            logger.warning("Could not find current model button, retrying...")
            jsleep(1.0, 2.0)
            continue
            
        logger.info(f"Opening model menu to check settings (attempt {attempt+1})")
        click_image(current_btn, timeout=2)
        jsleep(1.5, 2.0)
        
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

    except Exception as e:
        logger.error(f"Error processing {q['filename']}: {e}")
        traceback.print_exc()
        update_question_status(
            csv_path, q["filename"], STATUS_FAILED, error_msg=str(e)
        )
        return False


# ===================================================================
#  Main loop
# ===================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Auto Gemini Explanation")
    parser.add_argument("--manual-send", action="store_true",
                        help="Wait for human to press send")
    parser.add_argument("--start-from", type=str,
                        help="Start from a specific filename")
    parser.add_argument("--dry-run", action="store_true",
                        help="Just list pending questions, don't run")
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

    # --- Open panel once ---
    open_side_panel()
    jsleep(2.0, 3.0)

    chat_count = 0
    consecutive_fails = 0

    for q in pending:
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
                break

        success = process_question(q, manual_send=args.manual_send)

        if success:
            consecutive_fails = 0
            logger.info("Cooldown 5s…")
            jsleep(5, 5)
        else:
            consecutive_fails += 1
            if consecutive_fails >= 3:
                logger.critical("3 consecutive failures — halting.")
                beep_alert()
                break
            logger.warning(f"Fail #{consecutive_fails}. Attempting recovery…")
            # Recovery: reopen side panel
            open_side_panel()
            jsleep(2.0, 3.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("使用者強制中止程式 (KeyboardInterrupt)，安全退出。")
        sys.exit(0)
