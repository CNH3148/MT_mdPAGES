"""
Shared utilities for the data_MD_update pipeline.

Provides:
- YAML frontmatter parsing (without PyYAML dependency)
- CSV topic list reading/writing
- Path resolution helpers
- Dataview block extraction
"""

import csv
import os
import re
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("data_MD_update")

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# Directories to skip when scanning subjects
SKIP_DIRS: set[str] = {
    ".obsidian", "_attachments", "_templates", "data_MD_update",
}
SKIP_FILES: set[str] = {"_report.txt"}

TOPICS_SUBDIR: str = "_topics"

CSV_FILENAME: str = "topic_list.csv"
REFERENCE_FILENAME: str = "reference_for_ai.txt"
OLD_MD_DIR: str = "old_MD"
NEW_MD_DIR: str = "new_MD"

# CSV column names
CSV_COLUMNS: list[str] = [
    "Priority", "Subject", "TopicName", "TopicPath",
    "TotalQuestions", "IncludedQuestions", "SupportRate",
    "IsStub", "Status", "Note", "UpdatedAt",
]

# Valid statuses
STATUS_PENDING: str = "Pending"
STATUS_IN_PROGRESS: str = "InProgress"
STATUS_VALIDATED: str = "Validated"
STATUS_COMPLETED: str = "Completed"
STATUS_FAILED: str = "Failed"


def get_data_md_root(script_dir: Optional[Path] = None) -> Path:
    """Return the parent of data_MD_update, i.e. the data_MD root.

    When deployed, the layout is::

        data_MD/            ← this is what we return
        ├── data_MD_update/ ← where scripts live
        ├── 生物化學與臨床生化學/
        └── ...

    Parameters
    ----------
    script_dir : Path, optional
        The directory where the calling script lives. If *None*, inferred
        from the ``__file__`` of the caller (falls back to cwd).
    """
    if script_dir is None:
        script_dir = Path(__file__).resolve().parent
    return script_dir.parent


def get_update_dir(script_dir: Optional[Path] = None) -> Path:
    """Return the data_MD_update directory itself."""
    if script_dir is None:
        script_dir = Path(__file__).resolve().parent
    return script_dir


def list_subject_dirs(data_md_root: Path) -> list[Path]:
    """Return sorted list of subject directories under *data_md_root*."""
    subjects: list[Path] = []
    for entry in sorted(data_md_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in SKIP_DIRS:
            continue
        # A valid subject dir must contain a _topics sub-directory
        if (entry / TOPICS_SUBDIR).is_dir():
            subjects.append(entry)
    return subjects


# ---------------------------------------------------------------------------
# Lightweight YAML frontmatter parser (no PyYAML dependency)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"\A\s*---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n",
    re.DOTALL,
)


def parse_frontmatter(filepath: Path) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a Markdown file.

    Returns (metadata_dict, body_text).
    The parser handles the specific subset of YAML used in this project:
    - simple key: value pairs
    - single-quoted strings  ``topic: '[[name]]'``
    - boolean true/false
    - lists in ``[...]`` or ``- item`` form
    - multiline strings (joined)

    Raises
    ------
    ValueError
        If no frontmatter block is found.
    """
    content = filepath.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        raise ValueError(f"No YAML frontmatter found in {filepath}")

    yaml_text: str = match.group(1)
    body: str = content[match.end():]
    metadata: dict[str, Any] = _parse_yaml_block(yaml_text)
    return metadata, body


def _parse_yaml_value(raw: str) -> Any:
    """Convert a raw YAML value string to a Python object."""
    val = raw.strip()

    # Boolean
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False

    # Inline list  [a, b, c]  or  []
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_value(v) for v in inner.split(",")]

    # Quoted string (single or double)
    if (val.startswith("'") and val.endswith("'")) or \
       (val.startswith('"') and val.endswith('"')):
        return val[1:-1]

    # Integer
    try:
        return int(val)
    except ValueError:
        pass

    # Float
    try:
        return float(val)
    except ValueError:
        pass

    # Plain string
    return val


def _parse_yaml_block(text: str) -> dict[str, Any]:
    """Parse a simple YAML block into a dict."""
    result: dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: Optional[list[Any]] = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List item continuation  "- value"
        if stripped.startswith("- ") and current_key is not None:
            item_val = stripped[2:].strip()
            if current_list is None:
                current_list = []
                result[current_key] = current_list
            current_list.append(_parse_yaml_value(item_val))
            continue

        # key: value
        colon_pos = stripped.find(":")
        if colon_pos > 0:
            key = stripped[:colon_pos].strip()
            val_part = stripped[colon_pos + 1:].strip()
            current_key = key
            current_list = None

            if val_part:
                parsed = _parse_yaml_value(val_part)
                if isinstance(parsed, list):
                    current_list = parsed
                result[key] = parsed
            else:
                # Value might be on next lines (multiline / list)
                result[key] = ""

    return result


def get_raw_frontmatter_text(filepath: Path) -> str:
    """Extract the raw frontmatter text (including --- delimiters)."""
    content = filepath.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        raise ValueError(f"No YAML frontmatter found in {filepath}")
    # Return including the delimiters
    return content[: match.end()].rstrip("\n").rstrip("\r")


# ---------------------------------------------------------------------------
# Dataview block extraction
# ---------------------------------------------------------------------------

_DATAVIEW_RE = re.compile(
    r"```dataview\s*\r?\n(.*?)```",
    re.DOTALL,
)


def extract_dataview_block(filepath: Path) -> Optional[str]:
    """Extract the full dataview code block (including fences) from a file.

    Returns the matched text or *None* if no dataview block is found.
    """
    content = filepath.read_text(encoding="utf-8")
    match = _DATAVIEW_RE.search(content)
    if match is None:
        return None
    return match.group(0).strip()


# ---------------------------------------------------------------------------
# Stub detection
# ---------------------------------------------------------------------------

_ANALYSIS_HEADINGS = {"核心趨勢", "高頻考點", "關鍵字反射表", "Anki"}


def is_stub_topic(filepath: Path, size_threshold: int = 2000) -> bool:
    """Determine whether a topic file is a stub (no analysis content).

    A file is considered a stub if:
    - Its size is below *size_threshold* bytes, OR
    - It does not contain any of the analysis section headings.
    """
    if filepath.stat().st_size < size_threshold:
        return True
    content = filepath.read_text(encoding="utf-8")
    for heading in _ANALYSIS_HEADINGS:
        if heading in content:
            return False
    return True


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def read_topic_list(csv_path: Path) -> list[dict[str, str]]:
    """Read the topic_list.csv and return a list of row dicts."""
    if not csv_path.exists():
        return []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def write_topic_list(csv_path: Path, rows: list[dict[str, str]]) -> None:
    """Write rows to topic_list.csv."""
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def update_topic_status(
    csv_path: Path,
    subject: str,
    topic_name: str,
    status: str,
    note: str = "",
    updated_at: str = "",
) -> None:
    """Update the status of a specific topic in the CSV."""
    rows = read_topic_list(csv_path)
    for row in rows:
        if row["Subject"] == subject and row["TopicName"] == topic_name:
            row["Status"] = status
            if note:
                row["Note"] = note
            if updated_at:
                row["UpdatedAt"] = updated_at
            break
    write_topic_list(csv_path, rows)
