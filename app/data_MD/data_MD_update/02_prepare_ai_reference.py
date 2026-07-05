"""
02_prepare_ai_reference.py
==========================
Pick the highest-priority topic from ``topic_list.csv``, back up the old
topic file, and generate ``reference_for_ai.txt`` containing everything
the AI needs to write a new version.

Usage::

    python 02_prepare_ai_reference.py
    python 02_prepare_ai_reference.py --data-root /path/to/data_MD
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
    REFERENCE_FILENAME,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
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

_YEAR_DIR_RE = re.compile(r"^\d{3}-[12]$")

# Taiwan timezone (UTC+8)
_TW_TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Select target topic
# ---------------------------------------------------------------------------


def _select_target(rows: list[dict[str, str]]) -> dict[str, str] | None:
    """Select the topic to prepare.

    Priority:
    1. First ``InProgress`` entry (resume interrupted work).
    2. Highest-priority ``Pending`` entry.
    """
    in_progress = [r for r in rows if r["Status"] == STATUS_IN_PROGRESS]
    if in_progress:
        return in_progress[0]

    pending = [r for r in rows if r["Status"] == STATUS_PENDING]
    if not pending:
        return None

    # rows are already sorted by priority descending from 01_generate
    return pending[0]


# ---------------------------------------------------------------------------
# Gather questions
# ---------------------------------------------------------------------------


def _gather_questions(
    subject_dir: Path,
    topic_name: str,
) -> list[dict[str, str]]:
    """Collect all question files that belong to *topic_name*."""
    questions: list[dict[str, str]] = []

    for year_dir in sorted(subject_dir.iterdir()):
        if not year_dir.is_dir():
            continue
        if not _YEAR_DIR_RE.match(year_dir.name):
            continue

        for qfile in sorted(year_dir.glob("*.md")):
            try:
                meta, body = parse_frontmatter(qfile)
            except (ValueError, OSError):
                continue

            if meta.get("type") != "question":
                continue

            raw_topic: str = str(meta.get("topic", ""))
            q_topic = raw_topic.strip("'\"[] ")
            if q_topic != topic_name:
                continue

            # Extract choices as text
            choices_raw = meta.get("choices", [])
            if isinstance(choices_raw, list):
                choices_text = "\n".join(f"  {c}" for c in choices_raw)
            else:
                choices_text = str(choices_raw)

            questions.append({
                "year": str(meta.get("year", "")),
                "question_number": str(meta.get("question_number", "")),
                "question": str(meta.get("question", "")),
                "choices": choices_text,
                "answer": str(meta.get("answer", "")),
                "key_concept": str(meta.get("key_concept", "")),
                "summarize_including": str(meta.get("summarize_including", "")),
                "filepath": str(qfile.relative_to(subject_dir.parent)),
            })

    # Sort: year descending, question_number ascending
    questions.sort(
        key=lambda q: (-_year_sort_key(q["year"]), int(q["question_number"] or 0)),
    )
    return questions


def _year_sort_key(year_str: str) -> float:
    """Convert '115-1' to 115.1 for sorting."""
    try:
        parts = year_str.split("-")
        return float(parts[0]) + float(parts[1]) * 0.1
    except (IndexError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Generate reference file
# ---------------------------------------------------------------------------


def _generate_reference(
    target: dict[str, str],
    topic_file: Path,
    questions: list[dict[str, str]],
    output_path: Path,
    update_dir: Path,
) -> None:
    """Write reference_for_ai.txt."""
    subject = target["Subject"]
    topic_name = target["TopicName"]
    total_q = int(target["TotalQuestions"])
    included_q = int(target["IncludedQuestions"])
    new_q = total_q - included_q
    support_pct = float(target["SupportRate"]) * 100
    is_stub = target["IsStub"] == "True"
    file_type = "全新生成 (此 topic 尚無分析內容)" if is_stub else "擴充更新 (在舊報告基礎上整合新題目)"

    # Read old topic content
    try:
        old_content = topic_file.read_text(encoding="utf-8")
    except OSError:
        old_content = "(無法讀取舊文件)"

    # Extract YAML and dataview blocks
    try:
        meta, _ = parse_frontmatter(topic_file)
    except ValueError:
        meta = {}

    dataview_block = extract_dataview_block(topic_file) or "(未找到 Dataview 區塊)"

    # Build YAML block text
    yaml_lines = [
        "---",
        f"type: {meta.get('type', 'topic')}",
        f"subject: {meta.get('subject', subject)}",
        f"definition: {meta.get('definition', '')}",
        f"is_pinned: {'true' if meta.get('is_pinned') else 'false'}",
        f"aliases: {meta.get('aliases', '[]')}",
        "---",
    ]
    yaml_block = "\n".join(yaml_lines)

    # Build output path hint
    new_file_rel = f"data_MD_update/{NEW_MD_DIR}/{subject}/{topic_name}.md"

    lines: list[str] = []
    lines.append("═" * 60)
    lines.append("  TOPIC 更新參考資料")
    lines.append("═" * 60)
    lines.append("")
    lines.append("■ 基本資訊")
    lines.append(f"  Topic 名稱  : {topic_name}")
    lines.append(f"  所屬科目    : {subject}")
    lines.append(f"  總題數      : {total_q}")
    lines.append(f"  已納入分析  : {included_q} (支持度: {support_pct:.1f}%)")
    lines.append(f"  新加入題數  : {new_q}")
    lines.append(f"  文件類型    : {file_type}")
    lines.append("")
    lines.append(f"  輸出路徑    : {new_file_rel}")
    lines.append("")
    lines.append("═" * 60)
    lines.append("")
    lines.append("■ YAML 區塊（必須原封不動保留在文件開頭）")
    lines.append("")
    lines.append(yaml_block)
    lines.append("")
    lines.append("═" * 60)
    lines.append("")
    lines.append("■ Dataview 區塊（腳本將自動補齊，請**不要**在輸出中包含此區塊）")
    lines.append("")
    lines.append("⚠️ 【絕對禁止生成】你不需要也不應該在結尾生成「## 包含題庫」或 Dataview 區塊。")
    lines.append("⚠️ 請在 Anki 卡片寫完後，直接結束回答即可。腳本會在背景自動接手補齊。")
    lines.append("")
    lines.append("═" * 60)
    lines.append("")

    if is_stub:
        lines.append("■ 舊 Topic 文件內容")
        lines.append("")
        lines.append("⚠️ 此 Topic 尚無分析內容（Stub），請根據所有題目全新生成完整報告。")
        lines.append("   舊文件僅含 YAML 定義與 Dataview 區塊，無核心趨勢、關鍵字反射表或 Anki 卡。")
        lines.append("")
    else:
        lines.append("■ 舊 Topic 文件內容")
        lines.append("")
        lines.append("⚠️ 以下內容是經過專家精心整理的分析報告；除非發現錯誤否則不得修改。")
        lines.append("⚠️ 你必須以此為基礎進行「增量擴充」，不得遺漏舊報告中的任何知識點。(可以改變敘述方式，但不得遺漏舊報告已整理出來的任何知識點)")
        lines.append("⚠️ 舊報告的關鍵字反射表列數只能增加不能減少。")
        lines.append("⚠️ 舊報告的 Anki 卡片只能增加不能減少。")
        lines.append("══════════════════════════════════════════")
        lines.append("")
        lines.append(old_content)
        lines.append("")

    lines.append("═" * 60)
    lines.append("")
    lines.append(f"■ 所有題目（共 {total_q} 題，依年份降序排列）")
    lines.append("")

    for q in questions:
        included = q["summarize_including"].lower() == "true"
        tag = "[已納入]" if included else "[新題目]"
        lines.append(f"--- {tag} {q['year']} 第{q['question_number']}題 ---")
        lines.append(f"題幹: {q['question']}")
        lines.append(f"選項:")
        lines.append(q["choices"])
        lines.append(f"正確答案: {q['answer']}")
        lines.append(f"考點: {q['key_concept']}")
        lines.append("")

    lines.append("═" * 60)
    lines.append("（參考資料結束）")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Generated %s (%d lines)", output_path.name, len(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare reference material for the highest-priority topic.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Path to the data_MD root directory.",
    )
    args = parser.parse_args()

    data_root: Path = args.data_root or get_data_md_root(_SCRIPT_DIR)
    update_dir: Path = get_update_dir(_SCRIPT_DIR)
    csv_path: Path = update_dir / CSV_FILENAME

    if not csv_path.exists():
        logger.error("topic_list.csv not found. Run 01_generate_topic_list.py first.")
        sys.exit(1)

    rows = read_topic_list(csv_path)
    target = _select_target(rows)

    if target is None:
        logger.info("No Pending or InProgress topics remain. All done!")
        sys.exit(0)

    subject = target["Subject"]
    topic_name = target["TopicName"]
    topic_rel_path = target["TopicPath"]

    logger.info("Selected topic: [%s] %s (priority=%s, status=%s)",
                subject, topic_name, target["Priority"], target["Status"])

    topic_file = data_root / topic_rel_path

    if not topic_file.exists():
        logger.error("Topic file not found: %s", topic_file)
        sys.exit(1)

    # --- Backup old file ---
    old_md_dir = update_dir / OLD_MD_DIR / subject
    old_md_dir.mkdir(parents=True, exist_ok=True)
    backup_path = old_md_dir / f"{topic_name}.md"

    if backup_path.exists():
        logger.info("Backup already exists, skipping: %s", backup_path)
    else:
        shutil.copy2(topic_file, backup_path)
        logger.info("Backed up to: %s", backup_path)

    # --- Ensure new_MD output dir exists ---
    new_md_dir = update_dir / NEW_MD_DIR / subject
    new_md_dir.mkdir(parents=True, exist_ok=True)

    # --- Gather all questions ---
    subject_dir = data_root / subject
    questions = _gather_questions(subject_dir, topic_name)
    logger.info("Gathered %d questions for topic '%s'", len(questions), topic_name)

    # --- Generate reference ---
    ref_path = update_dir / REFERENCE_FILENAME
    _generate_reference(target, topic_file, questions, ref_path, update_dir)

    # --- Update CSV status to InProgress ---
    now_str = datetime.now(tz=_TW_TZ).strftime("%Y-%m-%d %H:%M")
    update_topic_status(csv_path, subject, topic_name,
                        status=STATUS_IN_PROGRESS,
                        note=f"Started at {now_str}")

    logger.info("Status updated to InProgress.")
    logger.info("")
    logger.info("=" * 50)
    logger.info("  Next step: AI reads reference_for_ai.txt")
    logger.info("  and writes new file to:")
    logger.info("    %s/%s/%s/%s.md",
                update_dir.name, NEW_MD_DIR, subject, topic_name)
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
