"""從 JSON 題目檔案生成對應的 Markdown 檔案。

讀取指定目錄下的 JSON 題目檔案，根據既有 Markdown 模板格式，
為每一道題目生成包含正確 YAML frontmatter 與基本內容骨架的 .md 檔案。

Usage:
    uv run generate_md_from_json.py --json-dir <JSON目錄> --output-dir <輸出根目錄>
    uv run generate_md_from_json.py --json-dir ./data_MD/115-2_JSON --output-dir ./data_MD
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_json_file(json_path: Path) -> list[dict[str, Any]]:
    """讀取並解析一個 JSON 題目檔案。

    Args:
        json_path: JSON 檔案的路徑。

    Returns:
        解析後的題目列表。

    Raises:
        SystemExit: 當檔案讀取或 JSON 解析失敗時。
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data: list[dict[str, Any]] = json.load(f)
        logger.info("成功載入 %s (%d 道題目)", json_path.name, len(data))
        return data
    except (OSError, json.JSONDecodeError) as e:
        logger.error("無法讀取或解析 JSON 檔案 %s: %s", json_path, e)
        sys.exit(1)


def escape_yaml_string(value: str) -> str:
    """為 YAML 字串值進行必要的跳脫處理。

    若字串包含冒號、引號等特殊字元，用單引號包裹；
    若字串本身包含單引號，則用雙引號包裹。

    Args:
        value: 原始字串值。

    Returns:
        適合直接寫入 YAML 的字串。
    """
    special_chars = (":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "<", ">", "=", "!", "%", "@", "`")
    needs_quoting = (
        any(ch in value for ch in special_chars)
        or value.startswith("'")
        or value.startswith('"')
        or value.startswith("-")
        or value.startswith(" ")
        or value.endswith(" ")
    )

    if not needs_quoting:
        return value

    if "'" not in value:
        return f"'{value}'"
    # 字串含單引號時，使用雙引號包裹，並跳脫內部雙引號
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_yaml_frontmatter(question: dict[str, Any]) -> str:
    """根據題目資料建構 YAML frontmatter 區塊。

    依照既有的 Markdown 模板格式，產生包含 type、qid、exam_id、year、
    question_number、subject、question、choices、answer 等欄位的
    YAML frontmatter。difficulty、topic、key_concept 等欄位留空待後續填寫。

    Args:
        question: 單道題目的字典資料。

    Returns:
        完整的 YAML frontmatter 字串（含前後的 --- 分隔線）。
    """
    qid: str = question["qid"]
    exam_id: str = str(question["exam_id"])
    year: str = str(question["year"])
    question_number: int = question["question_number"]
    subject: str = question["subject"]
    question_text: str = question["question"]
    choices: list[str] = question["choices"]
    answer: str = question["answer"]

    lines: list[str] = [
        "---",
        "type: question",
        f"qid: {escape_yaml_string(qid)}",
        f"exam_id: '{exam_id}'",
        f"year: {escape_yaml_string(year)}",
        f"question_number: {question_number}",
        f"subject: {escape_yaml_string(subject)}",
        f"question: {escape_yaml_string(question_text)}",
        "choices:",
    ]

    for choice in choices:
        lines.append(f"- {escape_yaml_string(choice)}")

    lines.extend([
        f"answer: {escape_yaml_string(answer)}",
        "difficulty: ''",
        "topic: ''",
        "key_concept: ''",
        "summarize_including: true",
        "images: []",
        "---",
    ])

    return "\n".join(lines)


def build_markdown_body(question: dict[str, Any]) -> str:
    """根據題目資料建構 Markdown 內容本體。

    包含「題目」段落（完整題目與選項）及「筆記與詳解」段落
    （僅保留各子段落標題，內容留空）。

    Args:
        question: 單道題目的字典資料。

    Returns:
        Markdown 本體內容字串。
    """
    question_text: str = question["question"]
    choices: list[str] = question["choices"]
    answer: str = question["answer"]

    lines: list[str] = [
        "",
        "## 題目",
        "",
        question_text,
        "",
    ]

    for choice in choices:
        lines.append(choice)

    lines.extend([
        "",
        "> [!success]- 正確解答",
        f"> **{answer}**",
        "",
        "---",
        "",
        "## 筆記與詳解",
        "",
        "## (1) 快速破題",
        "",
        "",
        "---",
        "",
        "## (2) 詳解預備",
        "",
        "",
        "---",
        "",
        "## (3) 詳解",
        "",
        "",
        "---",
        "",
        "## (4) 縱向聯想",
        "",
        "",
        "---",
        "",
        "## (5) 橫向比較",
        "",
        "",
        "---",
        "",
    ])

    return "\n".join(lines)


def generate_markdown_file(
    question: dict[str, Any],
    output_dir: Path,
    dry_run: bool = False,
) -> Path | None:
    """為單一題目產生 Markdown 檔案。

    檔案命名格式: {exam_id}_{year}_{question_number}.md
    目錄結構: {output_dir}/{subject}/{year}/{filename}

    Args:
        question: 單道題目的字典資料。
        output_dir: 輸出的根目錄。
        dry_run: 若為 True，僅列印預計行為而不實際寫入。

    Returns:
        成功寫入時回傳檔案路徑，dry_run 或失敗時回傳 None。
    """
    subject: str = question["subject"]
    year: str = str(question["year"])
    exam_id: str = str(question["exam_id"])
    question_number: int = question["question_number"]

    # 建立目標目錄：{output_dir}/{subject}/{year}/
    target_dir: Path = output_dir / subject / year
    filename: str = f"{exam_id}_{year}_{question_number}.md"
    target_path: Path = target_dir / filename

    if target_path.exists():
        logger.warning("檔案已存在，跳過: %s", target_path)
        return None

    yaml_block: str = build_yaml_frontmatter(question)
    body: str = build_markdown_body(question)
    full_content: str = yaml_block + body

    if dry_run:
        logger.info("[DRY RUN] 預計建立: %s", target_path)
        return None

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        logger.info("已建立: %s", target_path)
        return target_path
    except OSError as e:
        logger.error("無法寫入檔案 %s: %s", target_path, e)
        return None


def process_json_directory(
    json_dir: Path,
    output_dir: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    """處理指定目錄下的所有 JSON 題目檔案。

    Args:
        json_dir: 包含 JSON 檔案的目錄。
        output_dir: 輸出 Markdown 檔案的根目錄。
        dry_run: 若為 True，僅列印預計行為而不實際寫入。

    Returns:
        包含統計資訊的字典 (created, skipped, errors)。
    """
    stats: dict[str, int] = {"created": 0, "skipped": 0, "errors": 0}

    json_files: list[Path] = sorted(json_dir.glob("*.json"))
    if not json_files:
        logger.warning("在 %s 中找不到任何 JSON 檔案", json_dir)
        return stats

    logger.info("找到 %d 個 JSON 檔案，開始處理...", len(json_files))

    for json_path in json_files:
        questions: list[dict[str, Any]] = load_json_file(json_path)

        for question in questions:
            if question.get("type") != "question":
                logger.debug("跳過非題目類型的項目: %s", question.get("type"))
                continue

            result: Path | None = generate_markdown_file(
                question, output_dir, dry_run=dry_run
            )
            if result is not None:
                stats["created"] += 1
            elif not dry_run:
                stats["skipped"] += 1

    return stats


def main() -> None:
    """主程式進入點。"""
    parser = argparse.ArgumentParser(
        description="從 JSON 題目檔案生成 Markdown 檔案",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "範例:\n"
            "  uv run generate_md_from_json.py \\\n"
            "    --json-dir ./data_MD/115-2_JSON \\\n"
            "    --output-dir ./data_MD\n"
        ),
    )
    parser.add_argument(
        "--json-dir",
        type=Path,
        required=True,
        help="包含 JSON 題目檔案的目錄路徑",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="輸出 Markdown 檔案的根目錄路徑",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="僅列印預計行為而不實際寫入檔案",
    )

    args = parser.parse_args()

    json_dir: Path = args.json_dir.resolve()
    output_dir: Path = args.output_dir.resolve()

    if not json_dir.is_dir():
        logger.error("JSON 目錄不存在: %s", json_dir)
        sys.exit(1)

    logger.info("JSON 來源目錄: %s", json_dir)
    logger.info("Markdown 輸出目錄: %s", output_dir)
    if args.dry_run:
        logger.info("--- DRY RUN 模式 ---")

    stats: dict[str, int] = process_json_directory(
        json_dir, output_dir, dry_run=args.dry_run
    )

    logger.info("=== 處理完畢 ===")
    logger.info("已建立: %d 個檔案", stats["created"])
    logger.info("已跳過: %d 個檔案 (已存在)", stats["skipped"])
    logger.info("錯  誤: %d 個", stats["errors"])


if __name__ == "__main__":
    main()
