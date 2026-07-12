"""
07_auto_update_topics.py — 全自動 Topic 更新串聯腳本
====================================================
單一腳本自動串聯完整流程：
  02 (準備 AI 參考資料) → 06-4 (Chrome AI Studio 自動化) → 03 (驗證與部署)

取代原先需要同時開三個終端機分別執行 05、02、06-4 的工作流。

使用方式：
  全自動：
    uv run --with pydirectinput --with pyautogui --with pyperclip \\
           --with pygetwindow --with opencv-python --with pillow \\
           python data_MD_topic_update/07_auto_update_topics.py

  半自動（你負責最後送出）：
    ... 07_auto_update_topics.py --manual-send

緊急中止：將滑鼠快速移到螢幕最左上角（pyautogui FAILSAFE）
"""

import argparse
import importlib.util
import logging
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ── 路徑設定 ──────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _utils import (
    CSV_FILENAME,
    NEW_MD_DIR,
    REFERENCE_FILENAME,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_VALIDATED,
    get_update_dir,
    read_topic_list,
    update_topic_status,
)

# 腳本路徑
SCRIPT_02 = _SCRIPT_DIR / "02_prepare_ai_reference.py"
SCRIPT_03 = _SCRIPT_DIR / "03_validate_and_deploy.py"
CHROME_SCRIPT = _SCRIPT_DIR / "06-4_GLM-5.2_edited_auto_chrome.py"

CSV_PATH = _SCRIPT_DIR / CSV_FILENAME
REF_FILE = _SCRIPT_DIR / REFERENCE_FILENAME

# ── 常數 ──────────────────────────────────────────────
MAX_FIX_RETRIES: int = 2          # FIX_PROMPT 最多重試次數
TOPIC_COOLDOWN: tuple[int, int] = (20, 45)    # 題間冷卻秒數
BLOCKED_COOLDOWN: tuple[int, int] = (60, 90)  # 被擋後冷卻秒數
MAX_AUTO_FAILURES: int = 3        # 連續被擋幾次後切半自動

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)
sys.stdout.reconfigure(encoding="utf-8")


# ── 動態載入 06-4 Chrome 自動化模組 ─────────────────────
def _load_chrome_module() -> Any:
    """動態載入 06-4 腳本作為模組。

    使用 importlib 因為檔名含有非法 Python 識別字元（連字號、小數點）。
    """
    if not CHROME_SCRIPT.exists():
        log.error("找不到 Chrome 自動化腳本: %s", CHROME_SCRIPT)
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("chrome_auto", str(CHROME_SCRIPT))
    if spec is None or spec.loader is None:
        log.error("無法建立模組 spec: %s", CHROME_SCRIPT)
        sys.exit(1)

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        log.error(
            "Chrome 自動化模組的依賴套件未安裝。請使用：\n"
            "  uv run --with pydirectinput --with pyautogui --with pyperclip "
            "--with pygetwindow --with opencv-python --with pillow "
            "python data_MD_topic_update/07_auto_update_topics.py"
        )
        sys.exit(1)
    return module


# ── 防止系統休眠 ──────────────────────────────────────
def prevent_system_sleep() -> None:
    """呼叫 Windows API 防止系統閒置休眠與關閉螢幕。"""
    try:
        import ctypes
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(
            0x80000000 | 0x00000001 | 0x00000002
        )
        log.info("已設定防止系統休眠。")
    except Exception as e:
        log.warning("無法設定防止系統休眠: %s", e)


# ── 選取下一個目標 ────────────────────────────────────
def select_next_target(
    rows: list[dict[str, str]],
) -> Optional[dict[str, str]]:
    """選取下一個要處理的 topic。

    優先序：InProgress > Pending（CSV 中的排列順序即為優先序）。
    """
    for r in rows:
        if r["Status"] == STATUS_IN_PROGRESS:
            return r
    for r in rows:
        if r["Status"] == STATUS_PENDING:
            return r
    return None


# ── 產生 FIX_PROMPT ─────────────────────────────────────
def generate_fix_prompt(topic_name: str, error_note: str) -> str:
    """根據驗證失敗原因產生修正請求 prompt。"""
    return (
        "[FIX_PROMPT]\n"
        f"Topic 名稱: {topic_name}\n\n"
        "上一次輸出的 Markdown 檔案未能通過嚴格的系統驗證。\n"
        "請針對以下錯誤原因進行修正，並重新輸出「完整」的 Markdown 檔案"
        "（包含所有的 YAML 屬性、分析內容與 Dataview 區塊）：\n\n"
        f"錯誤原因：\n{error_note}\n"
    )


# ── 查詢特定 topic 的狀態 ───────────────────────────────
def get_topic_status(
    topic_name: str, subject: str,
) -> tuple[str, str]:
    """從 CSV 取得特定 topic 的 Status 和 Note。"""
    rows = read_topic_list(CSV_PATH)
    for row in rows:
        if row["TopicName"] == topic_name and row["Subject"] == subject:
            return row["Status"], row.get("Note", "")
    return "", ""


# ── 主程式 ────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="全自動 Topic 更新串聯腳本（02 → 06-4 → 03）",
    )
    parser.add_argument(
        "--manual-send",
        action="store_true",
        help="半自動模式：腳本 setup + 貼上 prompt，由人類點 Run 送出",
    )
    args = parser.parse_args()

    prevent_system_sleep()

    # 載入 Chrome 自動化模組
    log.info("載入 Chrome 自動化模組...")
    chrome = _load_chrome_module()

    print("=" * 58)
    print("  Topic 更新全自動串聯 (07)")
    mode_label = "半自動 (--manual-send)" if args.manual_send else "全自動"
    print(f"  模式: {mode_label}")
    print("  緊急中止: 將滑鼠快速移到螢幕最左上角")
    print("=" * 58)

    # 啟動 Chrome
    chrome.launch_chrome_if_needed()

    forced_manual: bool = args.manual_send
    consecutive_blocked: int = 0
    completed_count: int = 0

    while True:
        try:
            # ── Step 1: 檢查剩餘題目 ─────────────────────
            rows = read_topic_list(CSV_PATH)
            target = select_next_target(rows)

            if target is None:
                log.info("🎉 所有 topic 已處理完畢！")
                log.info("   本次共完成 %d 題。", completed_count)
                break

            topic_name: str = target["TopicName"]
            subject: str = target["Subject"]
            current_status: str = target["Status"]

            log.info("=" * 58)
            log.info(">>> 目標 Topic: %s (科目: %s)", topic_name, subject)
            log.info("    狀態: %s", current_status)
            log.info("=" * 58)

            # ── Step 2: 準備 AI 參考資料 (呼叫 02) ──────
            if current_status != STATUS_IN_PROGRESS:
                log.info("[Step 2] 執行 02_prepare_ai_reference.py...")
                result = subprocess.run(
                    [sys.executable, str(SCRIPT_02)],
                    cwd=str(_SCRIPT_DIR.parent),
                )
                if result.returncode != 0:
                    log.error("02 腳本執行失敗！跳過此題。")
                    update_topic_status(
                        CSV_PATH, subject, topic_name,
                        status=STATUS_FAILED,
                        note="02_prepare failed",
                    )
                    continue

            # 讀取 reference_for_ai.txt
            if not REF_FILE.exists():
                log.error("找不到 %s", REF_FILE)
                break

            ref_text: str = REF_FILE.read_text(encoding="utf-8")
            ref_text_for_paste: str = (
                ref_text.replace("\r\n", "\n").replace("\n", "\r\n")
            )

            # ── Step 3-6: Chrome 自動化 + 驗證迴圈 ──────
            fix_count: int = 0

            while True:
                is_fix: bool = ref_text.startswith("[FIX_PROMPT]")

                if is_fix:
                    log.info("[Step 3] 送出修正請求 (FIX_PROMPT)...")
                else:
                    log.info("[Step 3] 設定新對話串...")

                # 非 FIX_PROMPT 才需要開新 chat
                if not is_fix:
                    setup_ok: bool = False
                    for attempt in range(1, 4):
                        try:
                            chrome.setup_new_chat_os()
                            chrome.jsleep(2.5, 4.0)
                            setup_ok = True
                            break
                        except Exception as e:
                            if attempt < 3:
                                log.warning(
                                    "第 %d 次 setup 失敗: %s，重試...",
                                    attempt, e,
                                )
                                chrome.jsleep(4, 7)
                            else:
                                chrome.human_takeover(
                                    f"setup 失敗已達 3 次: {e}"
                                )
                                setup_ok = True  # 人類接手後視為完成
                    if not setup_ok:
                        log.error("setup 未完成，跳過此題。")
                        break

                # ── Step 4: 送出 Prompt ──────────────────
                log.info("[Step 4] 送出 Prompt...")
                send_result: str = chrome.submit_prompt_os(
                    ref_text_for_paste, manual_send=forced_manual,
                )

                # 檢查是否被擋（全自動模式）
                if send_result != "manual":
                    img_status: str = chrome.check_submit_status_by_image()
                    if img_status == "likely_blocked":
                        consecutive_blocked += 1
                        log.error(
                            "[驗證] ❌ 疑似被擋 (連續 %d/%d)",
                            consecutive_blocked, MAX_AUTO_FAILURES,
                        )
                        if (
                            consecutive_blocked >= MAX_AUTO_FAILURES
                            and not forced_manual
                        ):
                            log.warning(
                                "🔔 連續失敗達上限，自動切換為半自動模式。"
                            )
                            forced_manual = True
                            chrome.beep_alert(5)
                            print("\n" + "🔔" * 25)
                            print(
                                "👉 全自動持續被擋，已切換【半自動模式】。"
                            )
                            print(
                                "👉 後續每題會先暫停等你親自送出。"
                            )
                            print(
                                "👉 （若想回全自動，重啟腳本並移除 "
                                "--manual-send）"
                            )
                            print("🔔" * 25 + "\n")

                        cd = random.uniform(*BLOCKED_COOLDOWN)
                        log.info("[冷卻] 被擋後等待 %.0fs...", cd)
                        chrome.jsleep(cd, cd + 5)
                        continue  # 重試同一個 prompt
                    else:
                        consecutive_blocked = 0

                # ── Step 5: 等待生成並提取 ───────────────
                log.info("[Step 5] 等待模型生成並提取...")
                md_content: Optional[str] = chrome.wait_and_extract_os()

                if not md_content:
                    log.error("❌ 無法取得內容，15-25 秒後重試...")
                    chrome.jsleep(15, 25)
                    continue

                # 儲存到正確的科目資料夾
                out_dir = _SCRIPT_DIR / NEW_MD_DIR / subject
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f"{topic_name}.md"
                out_file.write_text(md_content, encoding="utf-8")
                log.info("[Step 5] ✅ 已存檔: %s", out_file)

                # ── Step 6: 驗證與部署 ───────────────────
                log.info("[Step 6] 執行驗證...")
                subprocess.run(
                    [
                        sys.executable, str(SCRIPT_03),
                        "--validate-only", "--topic", topic_name,
                    ],
                )
                subprocess.run(
                    [sys.executable, str(SCRIPT_03), "--deploy-all"],
                )

                # 檢查驗證結果
                status, note = get_topic_status(topic_name, subject)

                if status == STATUS_FAILED:
                    fix_count += 1
                    log.warning(
                        "❌ 驗證失敗 (第 %d/%d 次): %s",
                        fix_count, MAX_FIX_RETRIES, note,
                    )
                    if fix_count > MAX_FIX_RETRIES:
                        log.error(
                            "Topic '%s' 修正超過 %d 次，跳過。",
                            topic_name, MAX_FIX_RETRIES,
                        )
                        break

                    # 產生 FIX_PROMPT 並重送
                    fix_prompt = generate_fix_prompt(topic_name, note)
                    REF_FILE.write_text(fix_prompt, encoding="utf-8")
                    ref_text = fix_prompt
                    ref_text_for_paste = (
                        ref_text.replace("\r\n", "\n")
                        .replace("\n", "\r\n")
                    )
                    log.info("[FIX] 已產出修正請求，準備重送...")
                    chrome.jsleep(3, 5)
                    continue
                else:
                    completed_count += 1
                    log.info(
                        "✅ Topic '%s' 完成！(累計 %d 題)",
                        topic_name, completed_count,
                    )
                    break

            # ── 題間冷卻 ────────────────────────────────
            cd = random.uniform(*TOPIC_COOLDOWN)
            log.info("[冷卻] 題間等待 %.0fs...", cd)
            chrome.jsleep(cd, cd + 5)

        except KeyboardInterrupt:
            log.info("收到中止訊號，安全退出。")
            log.info("本次共完成 %d 題。", completed_count)
            break
        except Exception as e:
            log.error("未預期的錯誤: %s", e)
            try:
                chrome.jsleep(4, 7)
            except Exception:
                time.sleep(5)


if __name__ == "__main__":
    main()
