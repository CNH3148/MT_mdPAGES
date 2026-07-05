"""
03_validate_and_deploy.py
=========================
Validate new topic files in ``new_MD/`` and optionally deploy them back
to the database.

Modes
-----
--validate-only   Validate the current InProgress topic; mark as Validated.
--deploy-all      Deploy ALL Validated topics into the database, then update
                  ``summarize_including`` on related question files.
(no flags)        Validate + deploy the current InProgress topic (one-shot).

Usage::

    python 03_validate_and_deploy.py --validate-only
    python 03_validate_and_deploy.py --deploy-all
    python 03_validate_and_deploy.py   # one-shot: validate + deploy
"""

import argparse
import logging
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _utils import (
    CSV_FILENAME,
    NEW_MD_DIR,
    OLD_MD_DIR,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_VALIDATED,
    extract_dataview_block,
    get_data_md_root,
    get_update_dir,
    parse_frontmatter,
    read_topic_list,
    update_topic_status,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

_TW_TZ = timezone(timedelta(hours=8))
_YEAR_DIR_RE = re.compile(r"^\d{3}-[12]$")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _count_anki_cards(content: str) -> int:
    """Count the number of Anki cards in the text by counting semicolons in the Anki block."""
    match = re.search(r"```anki\s*\r?\n(.*?)```", content, re.DOTALL | re.IGNORECASE)
    if not match:
        return 0
    anki_block = match.group(1)
    cards = [line for line in anki_block.splitlines() if line.strip() and ";" in line]
    return len(cards)


def _count_table_rows(content: str) -> int:
    """Count markdown table rows (lines starting with '|')."""
    return len([line for line in content.splitlines() if line.strip().startswith("|")])


def validate_topic(
    new_file: Path,
    old_file: Path,
    topic_name: str,
) -> list[str]:
    """Validate a new topic file against the old backup.

    Returns a list of error messages. Empty list means all checks passed.
    """
    errors: list[str] = []

    # --- Check 1: File existence ---
    if not new_file.exists():
        errors.append(f"[CHECK-1 FAIL] 新文件不存在: {new_file}")
        return errors  # Cannot continue without the file

    if not old_file.exists():
        errors.append(f"[CHECK-1 FAIL] 備份文件不存在: {old_file}")
        return errors

    # --- Parse both files ---
    try:
        new_meta, _ = parse_frontmatter(new_file)
    except ValueError as e:
        errors.append(f"[PARSE FAIL] 新文件 YAML 解析失敗: {e}")
        return errors

    try:
        old_meta, _ = parse_frontmatter(old_file)
    except ValueError as e:
        errors.append(f"[PARSE FAIL] 舊文件 YAML 解析失敗: {e}")
        return errors

    # --- Check 2: type consistency ---
    old_type = old_meta.get("type", "")
    new_type = new_meta.get("type", "")
    if new_type != old_type:
        errors.append(
            f"[CHECK-2 FAIL] YAML type 不一致: "
            f"舊='{old_type}' → 新='{new_type}'"
        )

    # --- Check 3: subject consistency ---
    old_subj = old_meta.get("subject", "")
    new_subj = new_meta.get("subject", "")
    if new_subj != old_subj:
        errors.append(
            f"[CHECK-3 FAIL] YAML subject 不一致: "
            f"舊='{old_subj}' → 新='{new_subj}'"
        )

    # --- Check 4: definition exists ---
    if "definition" not in new_meta:
        errors.append("[CHECK-4 FAIL] 新文件缺少 'definition' 欄位")

    # --- Check 5: is_pinned exists ---
    if "is_pinned" not in new_meta:
        errors.append("[CHECK-5 FAIL] 新文件缺少 'is_pinned' 欄位")

    # --- Check 6: aliases exists ---
    if "aliases" not in new_meta:
        errors.append("[CHECK-6 FAIL] 新文件缺少 'aliases' 欄位")

    # --- 自動補齊 Dataview 區塊 ---
    old_dv = extract_dataview_block(old_file)
    if old_dv:
        try:
            import re
            new_content = new_file.read_text(encoding="utf-8")
            
            # 移除結尾的空白與多餘空行
            new_content = new_content.rstrip()
            
            # ★ 新增：確保 Anki 區塊已正確閉合
            anki_open_count = len(re.findall(r'```Anki', new_content))
            if anki_open_count > 0:
                # 檢查 Anki 開啟後是否有對應的閉合
                anki_match = re.search(r'```Anki\s*\r?\n(.*?)```', new_content, re.DOTALL)
                if not anki_match:
                    logger.warning(f"  ⚠️ [{topic_name}] 偵測到未閉合的 Anki 區塊，自動補上 ```")
                    new_content += "\n```"
            
            # 無論 AI 是生成了 `## 包含題庫`、`# 包含題庫` 還是直接生成了 ````dataview`
            # 我們找到它們出現的第一個位置，然後把後面的所有東西全部截斷
            match = re.search(r'\n#+\s*包含題庫|```dataview', new_content, re.IGNORECASE)
            if match:
                new_content = new_content[:match.start()]
                
            # 確保結尾乾淨後，強制在最末尾附加上最正確的 Dataview 區塊
            new_content += f"\n\n## 包含題庫\n\n{old_dv}\n"
            
            # 寫回檔案，讓後續的驗證與部署都使用這份完美的內容
            new_file.write_text(new_content, encoding="utf-8")
        except Exception as e:
            errors.append(f"[自動補齊失敗] 無法將 Dataview 寫入新文件: {e}")

    # --- Check 12: Anki code block 完整性 ---
    try:
        current_content = new_file.read_text(encoding="utf-8")
        anki_opens = len(re.findall(r'```Anki', current_content))
        anki_match = re.search(r'```Anki\s*\r?\n(.*?)```', current_content, re.DOTALL)
        if anki_opens > 0 and not anki_match:
            errors.append(
                "[CHECK-12 FAIL] Anki 程式碼區塊缺少閉合的 ``` — "
                "這會導致後方的 dataview 語法被吞噬"
            )
    except OSError:
        pass

    # --- Check 7: Dataview block exact match ---
    new_dv = extract_dataview_block(new_file)

    if old_dv is None:
        errors.append("[CHECK-7 WARN] 舊文件中沒有 Dataview 區塊")
    elif new_dv is None:
        errors.append("[CHECK-7 FAIL] 新文件中缺少 Dataview 區塊")
    else:
        # Normalize whitespace for comparison
        old_norm = _normalize_dataview(old_dv)
        new_norm = _normalize_dataview(new_dv)
        if old_norm != new_norm:
            errors.append(
                "[CHECK-7 FAIL] Dataview 區塊不一致\n"
                f"  舊: {old_dv[:200]}...\n"
                f"  新: {new_dv[:200]}..."
            )

    # --- Check 8: Filename consistency ---
    if new_file.stem != topic_name:
        errors.append(
            f"[CHECK-8 FAIL] 檔名不一致: "
            f"預期='{topic_name}.md' → 實際='{new_file.name}'"
        )

    # --- Check 9: Anki card count ---
    try:
        old_content = old_file.read_text(encoding="utf-8")
        new_content = new_file.read_text(encoding="utf-8")
        
        old_anki_count = _count_anki_cards(old_content)
        new_anki_count = _count_anki_cards(new_content)
        if new_anki_count < old_anki_count:
            errors.append(
                f"[CHECK-9 FAIL] Anki 卡片流失: "
                f"舊檔有 {old_anki_count} 張，新檔僅 {new_anki_count} 張"
            )

        # --- Check 10: Table row count ---
        old_row_count = _count_table_rows(old_content)
        new_row_count = _count_table_rows(new_content)
        if new_row_count < old_row_count:
            errors.append(
                f"[CHECK-10 FAIL] 表格列數流失: "
                f"舊檔有 {old_row_count} 列，新檔僅 {new_row_count} 列"
            )
            
        # --- Check 11: Content length ---
        if len(new_content) < len(old_content) * 0.8:
            errors.append(
                f"[CHECK-11 WARN] 內容可能大幅流失: "
                f"新檔字數 ({len(new_content)}) 少於舊檔 ({len(old_content)}) 的 80%"
            )
    except OSError:
        pass

    return errors


def _normalize_dataview(text: str) -> str:
    """Normalize a dataview block for comparison.

    Strips trailing whitespace per line, normalizes line endings,
    and removes leading/trailing blank lines.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip() for line in lines]
    # Strip leading/trailing empty lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------


def deploy_topic(
    new_file: Path,
    target_path: Path,
    subject: str,
    topic_name: str,
    data_root: Path,
) -> list[str]:
    """Deploy a new topic file and update summarize_including.

    Returns a list of error messages (empty = success).
    """
    errors: list[str] = []

    # Copy new file to target location
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(new_file, target_path)
        logger.info("  Deployed: %s", target_path)
    except OSError as e:
        errors.append(f"[DEPLOY FAIL] 無法複製文件: {e}")
        return errors

    # --- Post-deploy verification ---
    post_errors = _post_deploy_verify(target_path, new_file)
    if post_errors:
        errors.extend(post_errors)
        return errors

    # --- Update summarize_including on question files ---
    updated_count = _update_summarize_including(data_root, subject, topic_name)
    logger.info("  Updated summarize_including on %d question file(s)", updated_count)

    return errors


def _post_deploy_verify(deployed_file: Path, source_file: Path) -> list[str]:
    """Re-read the deployed file and verify it matches the source."""
    errors: list[str] = []

    try:
        deployed_meta, _ = parse_frontmatter(deployed_file)
        source_meta, _ = parse_frontmatter(source_file)
    except ValueError as e:
        errors.append(f"[POST-VERIFY FAIL] 部署後驗證解析失敗: {e}")
        return errors

    if deployed_meta.get("type") != source_meta.get("type"):
        errors.append("[POST-VERIFY FAIL] 部署後 type 不一致")
    if deployed_meta.get("subject") != source_meta.get("subject"):
        errors.append("[POST-VERIFY FAIL] 部署後 subject 不一致")

    deployed_dv = extract_dataview_block(deployed_file)
    source_dv = extract_dataview_block(source_file)
    if deployed_dv and source_dv:
        if _normalize_dataview(deployed_dv) != _normalize_dataview(source_dv):
            errors.append("[POST-VERIFY FAIL] 部署後 Dataview 不一致")

    return errors


def _update_summarize_including(
    data_root: Path,
    subject: str,
    topic_name: str,
) -> int:
    """Set summarize_including to true for all questions of this topic.

    Returns the count of updated files.
    """
    subject_dir = data_root / subject
    updated = 0

    for year_dir in sorted(subject_dir.iterdir()):
        if not year_dir.is_dir():
            continue
        if not _YEAR_DIR_RE.match(year_dir.name):
            continue

        for qfile in year_dir.glob("*.md"):
            try:
                meta, _ = parse_frontmatter(qfile)
            except (ValueError, OSError):
                continue

            if meta.get("type") != "question":
                continue

            raw_topic: str = str(meta.get("topic", ""))
            q_topic = raw_topic.strip("'\"[] ")
            if q_topic != topic_name:
                continue

            if meta.get("summarize_including") is True:
                continue  # Already true, skip

            # Replace summarize_including: false → true in the file
            content = qfile.read_text(encoding="utf-8")
            new_content = content.replace(
                "summarize_including: false",
                "summarize_including: true",
                1,  # Only first occurrence (in YAML)
            )
            if new_content != content:
                qfile.write_text(new_content, encoding="utf-8")
                updated += 1

    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and deploy new topic files.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate; mark as Validated but do not deploy.",
    )
    parser.add_argument(
        "--deploy-all",
        action="store_true",
        help="Deploy all Validated topics at once.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Path to the data_MD root directory.",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help="Specify a specific topic to validate, ignoring InProgress check.",
    )
    args = parser.parse_args()

    data_root: Path = args.data_root or get_data_md_root(_SCRIPT_DIR)
    update_dir: Path = get_update_dir(_SCRIPT_DIR)
    csv_path: Path = update_dir / CSV_FILENAME

    if not csv_path.exists():
        logger.error("topic_list.csv not found. Run 01_generate_topic_list.py first.")
        sys.exit(1)

    now_str = datetime.now(tz=_TW_TZ).strftime("%Y-%m-%d %H:%M")

    if args.deploy_all:
        _deploy_all_validated(data_root, update_dir, csv_path, now_str)
    else:
        _validate_current(data_root, update_dir, csv_path, now_str,
                          deploy=not args.validate_only, topic=args.topic)


def _validate_current(
    data_root: Path,
    update_dir: Path,
    csv_path: Path,
    now_str: str,
    deploy: bool,
    topic: str = None,
) -> None:
    """Validate (and optionally deploy) the current InProgress topic."""
    rows = read_topic_list(csv_path)

    # Find target topic
    target = None
    if topic:
        for r in rows:
            if r["TopicName"] == topic:
                target = r
                break
    else:
        for r in rows:
            if r["Status"] == STATUS_IN_PROGRESS:
                target = r
                break

    if target is None:
        logger.error("No InProgress topic found. Run 02_prepare_ai_reference.py first.")
        sys.exit(1)

    subject = target["Subject"]
    topic_name = target["TopicName"]

    logger.info("Validating: [%s] %s", subject, topic_name)

    new_file = update_dir / NEW_MD_DIR / subject / f"{topic_name}.md"
    old_file = update_dir / OLD_MD_DIR / subject / f"{topic_name}.md"

    errors = validate_topic(new_file, old_file, topic_name)

    if errors:
        logger.error("Validation FAILED with %d error(s):", len(errors))
        for e in errors:
            logger.error("  %s", e)
        update_topic_status(csv_path, subject, topic_name,
                            status=STATUS_FAILED,
                            note=" | ".join(errors),
                            updated_at=now_str)
        sys.exit(1)

    logger.info("Validation PASSED (8/8 checks).")

    if deploy:
        # One-shot mode: validate + deploy immediately
        target_path = data_root / subject / "_topics" / f"{topic_name}.md"
        deploy_errors = deploy_topic(new_file, target_path, subject,
                                     topic_name, data_root)
        if deploy_errors:
            logger.error("Deployment FAILED:")
            for e in deploy_errors:
                logger.error("  %s", e)
            update_topic_status(csv_path, subject, topic_name,
                                status=STATUS_FAILED,
                                note=" | ".join(deploy_errors),
                                updated_at=now_str)
            sys.exit(1)

        update_topic_status(csv_path, subject, topic_name,
                            status=STATUS_COMPLETED,
                            note="Deployed successfully",
                            updated_at=now_str)
        logger.info("✅ [%s] %s — deployed and completed.", subject, topic_name)
    else:
        # Validate-only mode
        update_topic_status(csv_path, subject, topic_name,
                            status=STATUS_VALIDATED,
                            note="Validated, awaiting deployment",
                            updated_at=now_str)
        logger.info("✅ [%s] %s — validated (awaiting deployment).", subject, topic_name)


def _deploy_all_validated(
    data_root: Path,
    update_dir: Path,
    csv_path: Path,
    now_str: str,
) -> None:
    """Deploy all Validated topics at once."""
    rows = read_topic_list(csv_path)
    validated = [r for r in rows if r["Status"] == STATUS_VALIDATED]

    if not validated:
        logger.info("No Validated topics to deploy.")
        return

    logger.info("Deploying %d validated topic(s)...", len(validated))
    success_count = 0
    fail_count = 0

    for target in validated:
        subject = target["Subject"]
        topic_name = target["TopicName"]

        logger.info("")
        logger.info("--- Deploying [%s] %s ---", subject, topic_name)

        new_file = update_dir / NEW_MD_DIR / subject / f"{topic_name}.md"
        old_file = update_dir / OLD_MD_DIR / subject / f"{topic_name}.md"
        target_path = data_root / subject / "_topics" / f"{topic_name}.md"

        # Re-validate before deploying (safety check)
        errors = validate_topic(new_file, old_file, topic_name)
        if errors:
            logger.error("  Re-validation FAILED:")
            for e in errors:
                logger.error("    %s", e)
            update_topic_status(csv_path, subject, topic_name,
                                status=STATUS_FAILED,
                                note=" | ".join(errors),
                                updated_at=now_str)
            fail_count += 1
            continue

        deploy_errors = deploy_topic(new_file, target_path, subject,
                                     topic_name, data_root)
        if deploy_errors:
            logger.error("  Deployment FAILED:")
            for e in deploy_errors:
                logger.error("    %s", e)
            update_topic_status(csv_path, subject, topic_name,
                                status=STATUS_FAILED,
                                note=" | ".join(deploy_errors),
                                updated_at=now_str)
            fail_count += 1
            continue

        update_topic_status(csv_path, subject, topic_name,
                            status=STATUS_COMPLETED,
                            note="Deployed successfully",
                            updated_at=now_str)
        success_count += 1
        logger.info("  ✅ Completed.")

    logger.info("")
    logger.info("=" * 50)
    logger.info("  Deploy summary: %d success, %d failed, %d total",
                success_count, fail_count, len(validated))
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
