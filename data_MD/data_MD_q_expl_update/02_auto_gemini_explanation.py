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
# AccountManager — 多帳號輪替與額度恢復排程
# ---------------------------------------------------------------------------
class AccountManager:
    """管理多帳號輪替、追蹤額度恢復時間。"""

    ACCOUNTS: list[dict[str, Any]] = [
        {"icon": "user_icon_1.png", "profile": "user_profile_1.png", "id": 1},
        {"icon": "user_icon_2.png", "profile": "user_profile_2.png", "id": 2},
        {"icon": "user_icon_3.png", "profile": "user_profile_3.png", "id": 3},
    ]

    def __init__(self) -> None:
        self.current_account_id: Optional[int] = None
        self.recovery_times: dict[int, datetime] = {}

    def detect_current_account(self) -> Optional[int]:
        """掃描螢幕上的 user_icon 來辨識目前登入的帳號。"""
        for acct in self.ACCOUNTS:
            if locate_image(acct["icon"], timeout=2.0) is not None:
                logger.info(f"偵測到當前帳號: account {acct['id']} ({acct['icon']})")
                self.current_account_id = acct["id"]
                return acct["id"]
        logger.warning("無法偵測到任何 user_icon。")
        return None

    def ensure_account(self, expected_id: int) -> bool:
        """檢查當前帳號是否與 expected_id 一致，若不一致則切換回去。

        Returns True if account is correct (or successfully switched back).
        """
        actual_id = self.detect_current_account()
        if actual_id == expected_id:
            logger.info(f"帳號驗證通過: 仍為 account {expected_id}")
            return True

        logger.warning(
            f"帳號不一致! 預期 account {expected_id}, "
            f"實際 account {actual_id}。切換回去..."
        )
        return self.switch_to_account(expected_id)

    def switch_to_account(self, target_id: int) -> bool:
        """切換到指定帳號（點擊 user_icon → change_profile → user_profile_X）。"""
        target_acct = next(
            (a for a in self.ACCOUNTS if a["id"] == target_id), None
        )
        if target_acct is None:
            logger.error(f"找不到 account {target_id} 的設定。")
            return False

        # 先偵測目前是哪個帳號的 icon 在畫面上
        current_icon: Optional[str] = None
        for acct in self.ACCOUNTS:
            if locate_image(acct["icon"], timeout=2.0) is not None:
                current_icon = acct["icon"]
                break

        if current_icon is None:
            logger.error("無法找到任何 user_icon 來進行帳號切換。")
            return False

        logger.info(f"點擊 {current_icon} 開始切換至 account {target_id}...")
        if not click_image(current_icon, timeout=2):
            logger.error(f"無法點擊 {current_icon}，帳號切換中止。")
            return False
        jsleep(2.0, 3.0)

        if not click_image("change_profile.png", timeout=3):
            logger.error("無法點擊 change_profile.png，帳號切換中止。")
            return False
        jsleep(2.0, 3.0)

        if not click_image(target_acct["profile"], timeout=3):
            logger.error(
                f"無法點擊 {target_acct['profile']}，帳號切換中止。"
            )
            return False
        jsleep(5.0, 6.0)

        # 最終驗證：確認畫面上的帳號確實已切換
        verified_id = self.detect_current_account()
        if verified_id != target_id:
            logger.error(
                f"帳號切換驗證失敗: 預期 account {target_id}, "
                f"實際偵測到 account {verified_id}。"
            )
            return False

        logger.info(f"已成功切換並驗證 account {target_id}")
        return True

    def record_quota_exhausted(
        self, account_id: int, recovery_dt: Optional[datetime]
    ) -> None:
        """記錄該帳號額度耗盡，保存恢復時間。"""
        if recovery_dt is not None:
            self.recovery_times[account_id] = recovery_dt
            logger.info(
                f"Account {account_id} 額度耗盡，預計恢復時間: {recovery_dt}"
            )
        else:
            fallback_dt = datetime.now() + timedelta(hours=24)
            self.recovery_times[account_id] = fallback_dt
            logger.warning(
                f"Account {account_id} 額度耗盡但無法解析恢復時間，"
                f"暫設為 {fallback_dt}"
            )

    def get_next_available_account(self) -> Optional[int]:
        """找到恢復時間已過的帳號（不含當前帳號），按 1→2→3 順序輪詢。"""
        now = datetime.now()
        start_idx = 0
        if self.current_account_id is not None:
            start_idx = self.current_account_id  # 1-based, gives next index

        for i in range(len(self.ACCOUNTS)):
            idx = (start_idx + i) % len(self.ACCOUNTS)
            acct = self.ACCOUNTS[idx]
            acct_id = acct["id"]
            if acct_id == self.current_account_id:
                continue
            recovery = self.recovery_times.get(acct_id)
            if recovery is None or recovery <= now:
                logger.info(
                    f"Account {acct_id} 額度可用"
                    f"（恢復時間已過或從未耗盡）。"
                )
                return acct_id

        logger.info("目前沒有可用帳號（全部額度耗盡且恢復時間未到）。")
        return None

    def get_earliest_recovery(self) -> Optional[tuple[int, datetime]]:
        """返回恢復時間最早的 (account_id, recovery_datetime)。"""
        if not self.recovery_times:
            return None
        earliest_id = min(
            self.recovery_times, key=lambda k: self.recovery_times[k]
        )
        return earliest_id, self.recovery_times[earliest_id]

    def all_accounts_exhausted_over_12h(self) -> bool:
        """檢查是否所有帳號的恢復時間都超過現在起算 12 小時。"""
        now = datetime.now()
        threshold = timedelta(hours=12)

        for acct in self.ACCOUNTS:
            acct_id = acct["id"]
            recovery = self.recovery_times.get(acct_id)
            if recovery is None:
                return False
            if (recovery - now) <= threshold:
                return False

        return True


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
def force_restart_side_panel(
    account_mgr: Optional["AccountManager"] = None,
) -> None:
    """Force close and reopen the side panel to recover from UI glitches.

    After reopening, verifies that the logged-in account has not changed.
    """
    logger.info("Force restarting side panel (Alt+G x2) to recover UI state...")
    try:
        x, y = pyautogui.position()
        w, h = pyautogui.size()
        if x <= 10 or y <= 10 or x >= w - 10 or y >= h - 10:
            pyautogui.moveTo(w // 2, h // 2)
    except Exception:
        pass
    human_hotkey("alt", "g")  # Toggle
    jsleep(2.0, 3.0)
    open_side_panel()         # Ensure it is open

    # 重開後驗證帳號一致性
    if account_mgr is not None and account_mgr.current_account_id is not None:
        account_mgr.ensure_account(account_mgr.current_account_id)

# user_icon 圖片清單（用於偵測彈窗是否已開啟）
USER_ICON_IMAGES: list[str] = [
    "user_icon_1.png", "user_icon_2.png", "user_icon_3.png",
]


def _is_side_panel_open() -> bool:
    """判斷 Gemini 側邊欄是否已開啟。

    優先檢查 gemini_input_box；若不存在，則以 user_icon 作為備案
    （輸入框有時會當掉不顯示，但 user_icon 仍可見）。
    """
    if locate_image(
        ["gemini_input_box.png", "gemini_input_box_2.png"], timeout=1
    ) is not None:
        return True
    # 輸入框未偵測到 — 嘗試 user_icon 作為備案
    if locate_image(USER_ICON_IMAGES, timeout=1.5) is not None:
        logger.info(
            "gemini_input_box 未偵測到，但 user_icon 可見 — "
            "判定彈窗已開啟（輸入框可能當機）。"
        )
        return True
    return False


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

    if _is_side_panel_open():
        logger.info("Side panel is already open.")
        return

    for attempt in range(3):
        logger.info(f"Opening Gemini side panel (Alt+G) - Attempt {attempt+1}")
        human_hotkey("alt", "g")
        jsleep(2.0, 3.0)

        if _is_side_panel_open():
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
    if difficulty in ("適中", "困難", "非常困難") or not difficulty:
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
    """Click input box → construct prompt with skill prefix → paste question.
    
    If the input box is occupied by stale text (gemini_send_btn visible but
    gemini_input_box not found), try to clear it via the model-button offset.
    If the model button also cannot be found, submit the stale prompt, wait for
    the response to finish, then discard it by starting a new chat — this
    guarantees the UI returns to a clean state.
    """
    logger.info("Step 6: Clicking input box and clearing it")
    clicked_box = click_image(["gemini_input_box.png", "gemini_input_box_2.png"], timeout=3)
    if not clicked_box:
        logger.warning("Could not find empty input box. Checking if it is occupied...")
        if locate_image("gemini_send_btn.png", timeout=2) is not None:
            logger.info("gemini_send_btn detected -> input box is occupied. Attempting to clear it.")
            # 透過點擊模型按鈕上方一行高度的位置來點擊輸入框
            model_btn_loc = None
            for btn in ["switch_model_from_flash.png", "switch_model_from_pro.png", "switch_model_from_auto.png", "switch_model_from_flash-lite.png", "flash_thinking.png", "pro_thinking.png", "flash-lite_thinking.png"]:
                model_btn_loc = locate_image(btn, timeout=0.5)
                if model_btn_loc:
                    break
            
            if model_btn_loc:
                # 點擊模型按鈕上方約 40 pixels (一行高度)
                human_click(model_btn_loc.left + 50, model_btn_loc.top - 40)
                jsleep(0.8, 1.2)
            else:
                # 無法定位模型按鈕 — 直接送出殘留 prompt 並捨棄回覆，再開新對話
                logger.warning(
                    "Cannot locate model button. Submitting stale prompt to flush, "
                    "then discarding the response via new chat..."
                )
                click_image("gemini_send_btn.png", timeout=3)
                # 等待回覆結束 (stop_btn 出現再消失)
                _wait_for_generation_complete(timeout=240)
                jsleep(1.0, 2.0)
                # 開新對話以重置 UI
                start_new_chat()
                jsleep(1.0, 2.0)
                # 現在輸入框應該已經清空，走正常流程重新填入正確 prompt
                if not click_image(["gemini_input_box.png", "gemini_input_box_2.png"], timeout=5):
                    raise RuntimeError(
                        "Could not find input box even after flushing stale prompt and starting new chat"
                    )
                jsleep(0.8, 1.2)
        else:
            # input_box 和 send_btn 都找不到 — 輸入框可能 UI 當機
            # 嘗試透過 model button 偏移量定位並點擊輸入框區域
            logger.warning(
                "input_box 和 send_btn 都找不到（輸入框可能 UI 當機），"
                "嘗試透過 model button 偏移量定位..."
            )
            model_btn_loc = None
            for btn in [
                "switch_model_from_flash.png",
                "switch_model_from_pro.png",
                "switch_model_from_auto.png",
                "switch_model_from_flash-lite.png",
                "flash_thinking.png",
                "pro_thinking.png",
                "flash-lite_thinking.png",
            ]:
                model_btn_loc = locate_image(btn, timeout=0.5)
                if model_btn_loc:
                    break

            if model_btn_loc:
                # 點擊模型按鈕上方約 40 pixels（輸入框區域）
                human_click(model_btn_loc.left + 50, model_btn_loc.top - 40)
                jsleep(0.8, 1.2)
                logger.info(
                    "已透過 model button 偏移量點擊輸入框區域，繼續正常流程。"
                )
            else:
                raise RuntimeError("Could not find input box")

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


# Both visual variants of the stop button (model is still generating)
STOP_BTN_IMAGES = ["gemini_stop_btn.png", "gemini_stop_btn_2.png"]


# ---------------------------------------------------------------------------
# GeminiState — UI state detection
# ---------------------------------------------------------------------------
class GeminiState:
    """Gemini 側邊欄的 UI 狀態枚舉。"""
    IDLE = "IDLE"                             # 閒置（輸入框空，模型沒在思考）
    IDLE_INPUT_FROZEN = "IDLE_INPUT_FROZEN"   # 閒置但輸入框當機（live_mode_btn 可見，input_box 不可見）
    INPUT_OCCUPIED = "INPUT_OCCUPIED"         # 輸入框有文字（可按 send_btn）
    GENERATING = "GENERATING"                 # 模型正在思考（stop_btn 可見）
    RESPONSE_READY = "RESPONSE_READY"         # 回覆已完成（gemini_mark 出現且非 GENERATING）
    UNKNOWN = "UNKNOWN"                       # 無法判斷


def detect_gemini_state() -> str:
    """偵測當前 Gemini 側邊欄的 UI 狀態。

    優先順序:
      GENERATING > INPUT_OCCUPIED > RESPONSE_READY
      > IDLE (正常: input_box 可見)
      > IDLE_INPUT_FROZEN (異常: live_mode_btn 可見但 input_box 不可見)
      > UNKNOWN
    """
    has_stop = locate_image(STOP_BTN_IMAGES, timeout=1.5) is not None
    if has_stop:
        return GeminiState.GENERATING

    has_send = locate_image("gemini_send_btn.png", timeout=1.0) is not None
    if has_send:
        return GeminiState.INPUT_OCCUPIED

    has_live = locate_image("live_mode_btn.png", timeout=1.5) is not None
    has_mark = (locate_image("gemini_mark.png", timeout=1.0) is not None) or (locate_image("gemini_mark_2.png", timeout=1.0) is not None)

    if has_mark and has_live:
        return GeminiState.RESPONSE_READY
    if has_live:
        # live_mode_btn 可見 — 再確認輸入框是否正常
        has_input_box = locate_image(
            ["gemini_input_box.png", "gemini_input_box_2.png"], timeout=1.0
        ) is not None
        if has_input_box:
            return GeminiState.IDLE
        else:
            logger.warning(
                "live_mode_btn 可見但 gemini_input_box 不可見 — "
                "輸入框可能當機。"
            )
            return GeminiState.IDLE_INPUT_FROZEN
    if has_mark:
        return GeminiState.RESPONSE_READY

    return GeminiState.UNKNOWN


# ===================================================================
#  Step (9) — Submit
# ===================================================================
def submit_prompt(manual_send: bool = False) -> tuple[bool, Optional[float]]:
    """送出 prompt 並驗證是否成功。

    Returns:
        (success, submit_time) — success 表示是否確認送出成功；
        submit_time 是按下送出按鈕的時間戳（用於後續超時計算）。
    """
    if manual_send:
        logger.info("Manual-send mode — 請手動送出 prompt")
        beep_alert()
        deadline = time.time() + 60
        while time.time() < deadline:
            if locate_image(STOP_BTN_IMAGES, timeout=1) is not None:
                return True, time.time()
            jsleep(1.0, 1.5)
        logger.warning("manual-send 等待期間 stop_btn 從未出現")
        return False, None

    logger.info("Step 9: 送出 prompt")

    # 1) 確認 send_btn 存在（代表輸入框有文字可送出）
    send_loc = locate_image("gemini_send_btn.png", timeout=3)
    if send_loc is None:
        logger.error(
            "gemini_send_btn 不存在 — 輸入框可能沒有文字，無法送出 prompt"
        )
        return False, None

    # 2) 確認送出前沒有殘留的 stop_btn（前一題仍在生成中）
    pre_stop = locate_image(STOP_BTN_IMAGES, timeout=1) is not None
    if pre_stop:
        logger.warning(
            "送出前就偵測到 gemini_stop_btn — 前一個 prompt 可能仍在生成中！"
        )
        return False, None

    # 3) 點擊送出
    click_image("gemini_send_btn.png", timeout=3)
    submit_time = time.time()
    jsleep(1.0, 1.5)

    # 4) 驗證送出：send_btn 應消失，stop_btn 應出現（狀態轉換）
    logger.info("驗證 prompt 是否成功送出...")
    success = False
    deadline = time.time() + 15  # 15 秒驗證窗口
    while time.time() < deadline:
        has_send = locate_image("gemini_send_btn.png", timeout=0.5) is not None
        has_stop = locate_image(STOP_BTN_IMAGES, timeout=0.5) is not None
        has_skill = locate_image("skill_activated.png", timeout=0.5) is not None

        if has_stop and not has_send:
            if has_skill:
                logger.info(
                    "✓ 送出成功確認：send_btn 消失 + stop_btn 出現 + skill 觸發"
                )
            else:
                logger.info(
                    "✓ 送出成功確認：send_btn 消失 + stop_btn 出現（無 skill）"
                )
            success = True
            break
        jsleep(0.5, 1.0)

    if not success:
        logger.warning(
            "Prompt 送出驗證失敗（send_btn 未消失或 stop_btn 未出現）"
        )
        # 如果 stop_btn 出現了，先終止
        if click_image(STOP_BTN_IMAGES, timeout=2):
            logger.info("已點擊 stop_btn 終止殘留生成。")
            jsleep(1.5, 2.5)
        return False, None

    return True, submit_time


# ===================================================================
#  Generation wait helper (used by both wait_and_copy and input_prompt
#  flush logic)
# ===================================================================
def _wait_for_generation_complete(
    timeout: int = 240,
    submit_time: Optional[float] = None,
    max_total_wait: int = 300,
) -> str:
    """等待生成完成：gemini_stop_btn 消失且 live_mode_btn 出現。

    Args:
        timeout: 基礎等待超時秒數（從現在起算）。
        submit_time: prompt 送出的時間戳，用於計算硬上限。
        max_total_wait: 從 submit_time 起算的最大等待秒數（硬上限）。

    Returns:
        "ok"               — 生成完成，live_mode_btn 已出現
        "stuck_generating"  — 超時且 stop_btn 仍存在（模型可能卡住）
        "no_mark"           — stop_btn 消失但 live_mode_btn 未出現
        "timeout"           — 達到硬上限超時
    """
    deadline = time.time() + timeout
    hard_deadline = (submit_time or time.time()) + max_total_wait

    while time.time() < min(deadline, hard_deadline):
        if locate_image(STOP_BTN_IMAGES, timeout=1) is None:
            logger.info("gemini_stop_btn 未偵測到，驗證中...")
            jsleep(2.0, 3.0)
            if locate_image(STOP_BTN_IMAGES, timeout=2) is None:
                logger.info("確認 gemini_stop_btn 已消失。")
                # live_mode_btn 與 stop_btn 在同一位置，理論上應立即出現
                if locate_image("live_mode_btn.png", timeout=5) is not None:
                    logger.info(
                        "live_mode_btn 已出現 — 生成確認完成。"
                    )
                    return "ok"
                else:
                    logger.warning(
                        "live_mode_btn 未出現（stop_btn 已消失）。"
                    )
                    return "no_mark"
            else:
                logger.info("gemini_stop_btn 又出現了，繼續等待...")
        jsleep(3.0, 5.0)

    # 超時後：檢查最終狀態
    if locate_image(STOP_BTN_IMAGES, timeout=1) is not None:
        logger.warning(
            f"超時 — gemini_stop_btn 仍然存在"
            f"（模型可能卡住，已等待 {timeout}s / hard {max_total_wait}s）。"
        )
        return "stuck_generating"

    logger.warning(
        f"等待超時 ({timeout}s / hard {max_total_wait}s)。"
    )
    return "timeout"


# ===================================================================
#  ensure_clean_state — 確保 UI 處於乾淨狀態
# ===================================================================
def ensure_clean_state(
    account_mgr: Optional["AccountManager"] = None,
) -> None:
    """確保 Gemini 側邊欄處於乾淨的 IDLE 狀態，可以接受新 prompt。

    根據偵測到的狀態執行不同的清理動作：
    - GENERATING: 點擊 stop_btn 終止 → 開新對話
    - INPUT_OCCUPIED: 清空輸入框 → 開新對話
    - RESPONSE_READY / IDLE: 直接開新對話
    - UNKNOWN: force_restart_side_panel → 重試一次
    """
    state = detect_gemini_state()
    logger.info(f"ensure_clean_state: 當前偵測狀態 = {state}")

    if state == GeminiState.GENERATING:
        logger.warning("偵測到模型仍在生成中，點擊 stop_btn 終止...")
        clicked = click_image(STOP_BTN_IMAGES, timeout=3)
        if clicked:
            logger.info("已點擊 stop_btn，等待模型停止...")
            jsleep(3.0, 5.0)
        else:
            logger.warning("無法點擊 stop_btn，嘗試 force_restart...")
            force_restart_side_panel(account_mgr)
            jsleep(2.0, 3.0)
        # 終止後開新對話
        start_new_chat()
        jsleep(1.5, 2.0)

    elif state == GeminiState.INPUT_OCCUPIED:
        logger.warning("輸入框有殘留文字，清空後開新對話...")
        # 嘗試點擊輸入框並清空
        click_image(
            ["gemini_input_box.png", "gemini_input_box_2.png"], timeout=2
        )
        jsleep(0.3, 0.5)
        human_hotkey("ctrl", "a")
        jsleep(0.2, 0.3)
        human_press("backspace")
        jsleep(0.5, 1.0)
        start_new_chat()
        jsleep(1.5, 2.0)

    elif state == GeminiState.IDLE_INPUT_FROZEN:
        logger.warning(
            "偵測到輸入框當機（live_mode_btn 可見但 input_box 不可見），"
            "開新對話串以脫離當機狀態..."
        )
        start_new_chat()
        jsleep(1.5, 2.0)
        # 開新對話後驗證輸入框是否恢復
        if locate_image(
            ["gemini_input_box.png", "gemini_input_box_2.png"], timeout=3
        ) is None:
            logger.warning(
                "開新對話後輸入框仍未恢復，"
                "嘗試透過 model button 偏移量定位並點擊輸入框區域..."
            )
            # 與 input_prompt() 相同的定位方法
            model_btn_loc = None
            for btn in [
                "switch_model_from_flash.png",
                "switch_model_from_pro.png",
                "switch_model_from_auto.png",
                "switch_model_from_flash-lite.png",
                "flash_thinking.png",
                "pro_thinking.png",
                "flash-lite_thinking.png",
            ]:
                model_btn_loc = locate_image(btn, timeout=0.5)
                if model_btn_loc:
                    break

            if model_btn_loc:
                # 點擊模型按鈕上方約 40 pixels（輸入框區域）
                human_click(
                    model_btn_loc.left + 50, model_btn_loc.top - 40
                )
                jsleep(0.8, 1.2)
                # 清空可能的殘留文字
                human_hotkey("ctrl", "a")
                jsleep(0.2, 0.3)
                human_press("backspace")
                jsleep(0.5, 1.0)
                logger.info(
                    "已透過 model button 偏移量點擊並清空輸入框區域，"
                    "後續流程將正常嘗試輸入 prompt。"
                )
            else:
                # model button 也找不到 — 最後手段 force_restart
                logger.warning(
                    "model button 也無法定位，嘗試 force_restart..."
                )
                force_restart_side_panel(account_mgr)
                jsleep(2.0, 3.0)
                start_new_chat()
                jsleep(1.5, 2.0)

    elif state in (GeminiState.RESPONSE_READY, GeminiState.IDLE):
        logger.info(f"狀態正常 ({state})，開新對話。")
        start_new_chat()
        jsleep(1.5, 2.0)

    elif state == GeminiState.UNKNOWN:
        logger.warning("無法辨識 UI 狀態，嘗試 force_restart...")
        force_restart_side_panel(account_mgr)
        jsleep(2.0, 3.0)
        # 重試一次
        retry_state = detect_gemini_state()
        if retry_state == GeminiState.UNKNOWN:
            raise RuntimeError(
                "force_restart 後仍無法辨識 UI 狀態，無法繼續。"
            )
        logger.info(f"force_restart 後狀態 = {retry_state}，開新對話。")
        start_new_chat()
        jsleep(1.5, 2.0)


# ===================================================================
#  Steps (10)-(12) — Wait for response, scroll, copy
# ===================================================================
def wait_and_copy(
    model: str,
    submit_time: Optional[float] = None,
) -> str:
    """等待生成完成，捲動至 copy button，複製回應文字。

    Flow:
      1. Initial wait (model-dependent).
      2. Poll: gemini_stop_btn 消失 → live_mode_btn 出現
         （確認 prompt 已送出且模型完成思考）。
      3. Poll: gemini_mark 出現（確認回覆泡泡已渲染）。
      4. 捲動至 gemini_copy_btn，檢查 quota limit，複製。
    """
    initial_wait = 20 if model == "flash" else 40
    logger.info(f"Step 10: 等待 {initial_wait}s ({model})…")
    jsleep(initial_wait, initial_wait + 5)

    # --- Phase 1: stop_btn → live_mode_btn ---
    gen_result = _wait_for_generation_complete(
        timeout=240,
        submit_time=submit_time,
        max_total_wait=300,
    )

    if gen_result == "stuck_generating":
        raise RuntimeError(
            "模型思考超時（stop_btn 仍存在） — 可能當機，需重啟新對話"
        )
    elif gen_result == "timeout":
        raise RuntimeError(
            "等待生成完成超時（5 分鐘硬上限） — 可能送出失敗或模型異常"
        )
    elif gen_result == "no_mark":
        # stop_btn 消失但 live_mode_btn 未出現 — 可能 UI glitch
        logger.warning(
            "stop_btn 消失但 live_mode_btn 未出現，"
            "嘗試繼續（等待 gemini_mark 作為備案）..."
        )
    # gen_result == "ok" → 正常繼續
    jsleep(2.0, 3.0)

    # --- Phase 2: 等待 gemini_mark（回覆泡泡完全渲染）---
    logger.info("Step 11: 等待 gemini_mark/gemini_mark_2 確認回覆已渲染...")
    mark_loc = None
    mark_deadline = time.time() + 60  # 從 30s 延長至 60s
    while time.time() < mark_deadline:
        mark_loc = locate_image("gemini_mark.png", timeout=2) or locate_image("gemini_mark_2.png", timeout=2)
        if mark_loc is not None:
            logger.info("gemini_mark/gemini_mark_2 已偵測到。")
            break
        jsleep(1.0, 2.0)
    if mark_loc is None:
        raise RuntimeError(
            "gemini_mark 遲遲未出現（等待 60 秒） — "
            "可能送出失敗或回覆未渲染"
        )

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
        model = setup_model(q.get("difficulty", ""))

        submit_time: Optional[float] = None
        success_trigger = False
        for attempt in range(3):
            if attempt > 0:
                logger.info(f"Retrying prompt submission (Attempt {attempt+1})...")
                # 使用 ensure_clean_state 確保 UI 狀態乾淨
                try:
                    ensure_clean_state()
                except Exception as e:
                    logger.warning(f"ensure_clean_state 重試前失敗: {e}")
                    try:
                        start_new_chat()
                        jsleep(1.0, 2.0)
                    except Exception:
                        pass
            input_prompt(q)
            ok, t = submit_prompt(manual_send)
            if ok:
                submit_time = t
                success_trigger = True
                break

        if not success_trigger:
            raise RuntimeError("Failed to activate skill after multiple submit attempts")

        response = wait_and_copy(model, submit_time=submit_time)

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

    # --- 初始化帳號管理器 ---
    account_mgr = AccountManager()
    account_mgr.detect_current_account()
    if account_mgr.current_account_id is None:
        logger.warning("初始化時無法偵測到帳號 icon，將在首次額度事件時重新偵測。")

    chat_count = 0
    consecutive_fails = 0
    completed_count = 0
    failed_count = 0
    last_commit_time: float = time.time()
    commit_interval: int = args.commit_interval

    for q in pending:
        while True:
            logger.info(f"{'='*50}")
            logger.info(f"Processing: {q['filename']}  (difficulty={q['difficulty']})")
            update_question_status(csv_path, q["filename"], STATUS_IN_PROGRESS)

            # 確保 UI 處於乾淨狀態再處理新題目
            try:
                ensure_clean_state(account_mgr)
            except Exception as e:
                logger.error(f"ensure_clean_state 失敗: {e}")
                force_restart_side_panel(account_mgr)
                jsleep(2.0, 3.0)
                try:
                    ensure_clean_state(account_mgr)
                except Exception:
                    logger.critical(
                        "二次 ensure_clean_state 仍然失敗，終止腳本。"
                    )
                    beep_alert()
                    sys.exit(1)

            try:
                success = process_question(q, manual_send=args.manual_send)
            except QuotaLimitException:
                # --- 三帳號智能輪替與恢復排程 ---
                # 1. 解析畫面上的恢復時間
                recovery_text = attempt_read_recovery_text()
                logger.info(f"嘗試框選的恢復時間文字: {recovery_text.strip()}")
                recovery_dt = parse_quota_recovery_time(recovery_text)
                if recovery_dt is None:
                    jsleep(1.0, 2.0)
                    recovery_text = attempt_read_recovery_text()
                    logger.info(f"第二次嘗試: {recovery_text.strip()}")
                    recovery_dt = parse_quota_recovery_time(recovery_text)

                # 2. 記錄當前帳號的額度耗盡
                if account_mgr.current_account_id is None:
                    account_mgr.detect_current_account()
                if account_mgr.current_account_id is not None:
                    account_mgr.record_quota_exhausted(
                        account_mgr.current_account_id, recovery_dt
                    )

                # 3. 找下一個可用帳號
                next_acct = account_mgr.get_next_available_account()
                if next_acct is not None:
                    logger.info(f"切換至 account {next_acct} 繼續工作...")
                    if not account_mgr.switch_to_account(next_acct):
                        logger.critical("帳號切換失敗。終止腳本。")
                        ts = time.strftime("%Y-%m-%d %H:%M:%S")
                        update_question_status(csv_path, q["filename"], STATUS_FAILED, error_msg=f"Account Switch Failed at {ts}")
                        beep_alert()
                        sys.exit(1)
                    
                    # 剛切換完帳號不需要 alt+G（否則會導致帳號被重置回預設帳號，陷入切換迴圈）
                    jsleep(2.0, 3.0)
                    continue  # Retry this question

                # 4. 全部帳號耗盡 — 檢查是否超過 12 小時門檻
                if account_mgr.all_accounts_exhausted_over_12h():
                    logger.critical(
                        "三個帳號的恢復時間都超過 12 小時，終止腳本。"
                    )
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    update_question_status(csv_path, q["filename"], STATUS_FAILED, error_msg=f"All Accounts Quota Exhausted >12h at {ts}")
                    if args.auto_git:
                        logger.info("Performing final git commit before exit...")
                        git_commit_and_push(completed_count, failed_count)
                    beep_alert()
                    sys.exit(1)

                # 5. 等待最早恢復的帳號
                earliest = account_mgr.get_earliest_recovery()
                if earliest is None:
                    logger.critical("無法取得任何恢復時間。終止腳本。")
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    update_question_status(csv_path, q["filename"], STATUS_FAILED, error_msg=f"Missing Recovery Time at {ts}")
                    beep_alert()
                    sys.exit(1)

                target_id, target_recovery_dt = earliest
                wait_seconds = (
                    (target_recovery_dt - datetime.now()).total_seconds()
                )
                wait_seconds = max(wait_seconds, 0) + 300  # +5 分鐘緩衝

                logger.info(
                    f"等待 account {target_id} 恢復。"
                    f"預計恢復: {target_recovery_dt}，"
                    f"等待 {int(wait_seconds)} 秒..."
                )
                beep_alert()

                while wait_seconds > 0:
                    sleep_chunk = min(wait_seconds, 300)
                    jsleep(sleep_chunk, sleep_chunk)
                    wait_seconds -= sleep_chunk
                    if wait_seconds > 0:
                        logger.info(
                            f"持續等待中... 剩餘約 {int(wait_seconds)} 秒"
                        )

                logger.info(
                    f"等待結束。切換至 account {target_id} 繼續工作..."
                )
                if not account_mgr.switch_to_account(target_id):
                    logger.critical("帳號切換失敗。終止腳本。")
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    update_question_status(csv_path, q["filename"], STATUS_FAILED, error_msg=f"Account Switch Failed After Wait at {ts}")
                    beep_alert()
                    sys.exit(1)
                # 清除該帳號的恢復時間記錄
                account_mgr.recovery_times.pop(target_id, None)
                
                # 同理，剛切換完帳號不需要 alt+G
                jsleep(2.0, 3.0)
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
                    # --- 嘗試切換到其他帳號而非直接終止 ---
                    logger.warning(
                        f"連續失敗 {consecutive_fails} 次，"
                        "嘗試切換至其他可用帳號以繼續工作..."
                    )
                    switched = False
                    if account_mgr is not None:
                        next_id = account_mgr.get_next_available_account()
                        if next_id is not None:
                            logger.info(
                                f"準備從 account {account_mgr.current_account_id} "
                                f"切換至 account {next_id}..."
                            )
                            # force_restart 重開彈窗，確保 UI 乾淨
                            force_restart_side_panel(account_mgr)
                            jsleep(2.0, 3.0)
                            if account_mgr.switch_to_account(next_id):
                                logger.info(
                                    f"✓ 已切換至 account {next_id}，"
                                    "重置連續失敗計數，繼續執行。"
                                )
                                consecutive_fails = 0
                                switched = True
                                # 切換帳號後需重開彈窗以載入新帳號的 session
                                force_restart_side_panel(account_mgr)
                                jsleep(2.0, 3.0)
                            else:
                                logger.error(
                                    f"切換至 account {next_id} 失敗。"
                                )
                        else:
                            logger.warning("沒有其他可用帳號可切換。")
                    else:
                        logger.warning("account_mgr 未初始化，無法切換帳號。")

                    if not switched:
                        logger.critical(
                            f"連續失敗 {consecutive_fails} 次且無法切換帳號 — halting."
                        )
                        if args.auto_git:
                            logger.info("Performing final git commit before exit...")
                            git_commit_and_push(completed_count, failed_count)
                        beep_alert()
                        sys.exit(1)
                logger.warning(f"Fail #{consecutive_fails}. Attempting recovery…")
                # Recovery: 確保 UI 狀態乾淨
                try:
                    ensure_clean_state(account_mgr)
                except Exception as e:
                    logger.warning(f"ensure_clean_state 恢復失敗: {e}")
                    force_restart_side_panel(account_mgr)
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

                # 重開後驗證帳號一致性
                if account_mgr.current_account_id is not None:
                    account_mgr.ensure_account(account_mgr.current_account_id)
                
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
