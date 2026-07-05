"""
01_generate_topic_list.py
=========================
Scan all subject directories under the data_MD root, calculate the update
priority for each topic, and output ``topic_list.csv``.

Priority formula:
    priority = 0.5 * (total_questions / 80) + 0.5 * (1 - support_rate)

Usage::

    python 01_generate_topic_list.py            # default: scan parent dir
    python 01_generate_topic_list.py --data-root /path/to/data_MD
"""

import argparse
import logging
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the script's own directory is on sys.path so _utils can be imported
# regardless of the working directory.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _utils import (
    CSV_COLUMNS,
    CSV_FILENAME,
    STATUS_PENDING,
    TOPICS_SUBDIR,
    get_data_md_root,
    get_update_dir,
    is_stub_topic,
    list_subject_dirs,
    parse_frontmatter,
    write_topic_list,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Question scanning
# ---------------------------------------------------------------------------

# Year directories look like 103-1, 114-2, 115-1 etc.
_YEAR_DIR_RE = re.compile(r"^\d{3}-[12]$")


def _scan_questions_for_subject(subject_dir: Path) -> dict[str, dict[str, int]]:
    """Scan all question files under a subject directory.

    Returns a dict mapping topic_name -> {"total": N, "included": M}.
    """
    topic_stats: dict[str, dict[str, int]] = {}

    for year_dir in sorted(subject_dir.iterdir()):
        if not year_dir.is_dir():
            continue
        if not _YEAR_DIR_RE.match(year_dir.name):
            continue

        for qfile in year_dir.glob("*.md"):
            try:
                meta, _ = parse_frontmatter(qfile)
            except (ValueError, OSError) as exc:
                logger.warning("Skip %s: %s", qfile.name, exc)
                continue

            if meta.get("type") != "question":
                continue

            # Extract topic name from '[[topic_name]]'
            raw_topic: str = str(meta.get("topic", ""))
            topic_name = raw_topic.strip("'\"[] ")
            if not topic_name:
                continue

            if topic_name not in topic_stats:
                topic_stats[topic_name] = {"total": 0, "included": 0}

            topic_stats[topic_name]["total"] += 1

            if meta.get("summarize_including") is True:
                topic_stats[topic_name]["included"] += 1

    return topic_stats


# ---------------------------------------------------------------------------
# Priority calculation
# ---------------------------------------------------------------------------


def _calc_priority(total: int, included: int) -> float:
    """Calculate the update priority score."""
    support_rate = included / total if total > 0 else 0.0
    return 0.5 * (total / 80.0) + 0.5 * (1.0 - support_rate)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate topic_list.csv with update priorities.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Path to the data_MD root directory. "
             "Defaults to the parent of this script's directory.",
    )
    args = parser.parse_args()

    data_root: Path = args.data_root or get_data_md_root(_SCRIPT_DIR)
    update_dir: Path = get_update_dir(_SCRIPT_DIR)
    csv_path: Path = update_dir / CSV_FILENAME

    logger.info("Data MD root : %s", data_root)
    logger.info("Output CSV   : %s", csv_path)

    subjects = list_subject_dirs(data_root)
    if not subjects:
        logger.error("No subject directories found under %s", data_root)
        sys.exit(1)

    logger.info("Found %d subject(s):", len(subjects))
    for s in subjects:
        logger.info("  - %s", s.name)

    rows: list[dict[str, str]] = []

    for subject_dir in subjects:
        subject_name = subject_dir.name
        topics_dir = subject_dir / TOPICS_SUBDIR

        if not topics_dir.is_dir():
            logger.warning("  [SKIP] No _topics dir in %s", subject_name)
            continue

        # Scan questions to build stats
        question_stats = _scan_questions_for_subject(subject_dir)

        # Iterate topic files
        for topic_file in sorted(topics_dir.glob("*.md")):
            topic_name = topic_file.stem  # filename without .md
            stats = question_stats.get(topic_name, {"total": 0, "included": 0})
            total_q = stats["total"]
            included_q = stats["included"]
            support_rate = included_q / total_q if total_q > 0 else 0.0
            priority = _calc_priority(total_q, included_q)
            stub = is_stub_topic(topic_file)

            # Relative path from data_root
            rel_path = topic_file.relative_to(data_root).as_posix()

            rows.append({
                "Priority": f"{priority:.4f}",
                "Subject": subject_name,
                "TopicName": topic_name,
                "TopicPath": rel_path,
                "TotalQuestions": str(total_q),
                "IncludedQuestions": str(included_q),
                "SupportRate": f"{support_rate:.4f}",
                "IsStub": str(stub),
                "Status": STATUS_PENDING,
                "Note": "",
                "UpdatedAt": "",
            })

    # Sort by priority descending
    rows.sort(key=lambda r: float(r["Priority"]), reverse=True)

    write_topic_list(csv_path, rows)

    logger.info("Generated %s with %d topics.", csv_path.name, len(rows))

    # Print summary
    stub_count = sum(1 for r in rows if r["IsStub"] == "True")
    logger.info("  Stubs: %d / %d", stub_count, len(rows))
    if rows:
        logger.info("  Highest priority: %s — %s (score=%s)",
                     rows[0]["Subject"], rows[0]["TopicName"],
                     rows[0]["Priority"])
        logger.info("  Lowest  priority: %s — %s (score=%s)",
                     rows[-1]["Subject"], rows[-1]["TopicName"],
                     rows[-1]["Priority"])


if __name__ == "__main__":
    main()
