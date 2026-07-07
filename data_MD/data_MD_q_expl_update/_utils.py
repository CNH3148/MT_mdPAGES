"""
Shared utilities for the data_MD_q_expl_update pipeline.

Provides:
- Path resolution constants
- CSV question list reading/writing
- YAML frontmatter parsing (without PyYAML)
- Question and Explanation parsing
"""

import csv
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional, Dict, Tuple, List

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("data_MD_q_expl_update")

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def get_script_dir() -> Path:
    return Path(__file__).resolve().parent

DATA_ROOT: Path = get_script_dir().parent
IMAGE_DIR: Path = get_script_dir() / "images_AG"
OLD_TEMP_DIR: Path = get_script_dir() / "old_temp"
NEW_TEMP_DIR: Path = get_script_dir() / "new_temp"

CSV_FILENAME: str = "question_list.csv"

# Valid subjects (to scan)
SUBJECTS: List[str] = [
    "生物化學與臨床生化學",
    "臨床生理學與病理學",
    "臨床血液學與血庫學",
    "醫學分子檢驗學與臨床鏡檢學",
    "臨床血清免疫學與臨床病毒學",
    "臨床細菌學與臨床黴菌學"
]

# ---------------------------------------------------------------------------
# CSV and Status Constants
# ---------------------------------------------------------------------------
CSV_COLUMNS: List[str] = [
    "filename", "subject", "year", "exam_id", "question_number", 
    "difficulty", "relative_path", "status", "model_used", "error_msg"
]

STATUS_PENDING: str = "Pending"
STATUS_IN_PROGRESS: str = "InProgress"
STATUS_COMPLETED: str = "Completed"
STATUS_FAILED: str = "Failed"
STATUS_SKIPPED: str = "Skipped"

# ---------------------------------------------------------------------------
# Lightweight YAML frontmatter parser
# ---------------------------------------------------------------------------
_FRONTMATTER_RE = re.compile(
    r"\A\s*---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n",
    re.DOTALL,
)

def parse_frontmatter(filepath: Path) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from a Markdown file. Returns (metadata_dict, body_text)."""
    content = filepath.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        raise ValueError(f"No YAML frontmatter found in {filepath}")

    yaml_text: str = match.group(1)
    body: str = content[match.end():]
    metadata: Dict[str, Any] = _parse_yaml_block(yaml_text)
    return metadata, body

def _parse_yaml_value(raw: str) -> Any:
    val = raw.strip()
    if val.lower() == "true": return True
    if val.lower() == "false": return False
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner: return []
        return [_parse_yaml_value(v) for v in inner.split(",")]
    if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
        return val[1:-1]
    try: return int(val)
    except ValueError: pass
    try: return float(val)
    except ValueError: pass
    return val

def _parse_yaml_block(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: Optional[List[Any]] = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key is not None:
            item_val = stripped[2:].strip()
            if current_list is None:
                current_list = []
                result[current_key] = current_list
            current_list.append(_parse_yaml_value(item_val))
            continue
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
                result[key] = ""
    return result

# ---------------------------------------------------------------------------
# Markdown content parsing
# ---------------------------------------------------------------------------
def has_explanation(body_text: str) -> bool:
    """Check if '## 筆記與詳解' section has non-whitespace content after it."""
    parts = body_text.split("## 筆記與詳解")
    if len(parts) < 2:
        return False
    expl_content = parts[1].strip()
    return bool(expl_content)

def parse_question_components(body_text: str) -> Tuple[str, str, str, str, str, str]:
    """
    Extracts question text, options A, B, C, D, and answer from the body.
    Expects format:
    (Question Text)
    (A) ...
    (B) ...
    (C) ...
    (D) ...
    
    And 'answer: ...' from frontmatter (not handled here, answer usually is passed separately)
    """
    lines = body_text.splitlines()
    question_lines = []
    opt_a, opt_b, opt_c, opt_d = "", "", "", ""
    current_section = "question"
    
    for line in lines:
        if line.strip().startswith("## 筆記與詳解"):
            break
            
        stripped = line.strip()
        if stripped.startswith("(A)"):
            current_section = "A"
            opt_a = stripped[3:].strip()
        elif stripped.startswith("(B)"):
            current_section = "B"
            opt_b = stripped[3:].strip()
        elif stripped.startswith("(C)"):
            current_section = "C"
            opt_c = stripped[3:].strip()
        elif stripped.startswith("(D)"):
            current_section = "D"
            opt_d = stripped[3:].strip()
        else:
            if current_section == "question":
                if stripped:
                    question_lines.append(stripped)
            elif current_section == "A": opt_a += " " + stripped
            elif current_section == "B": opt_b += " " + stripped
            elif current_section == "C": opt_c += " " + stripped
            elif current_section == "D": opt_d += " " + stripped

    question_text = "\n".join(question_lines).strip()
    return question_text, opt_a, opt_b, opt_c, opt_d

# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def read_question_list(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)

def write_question_list(csv_path: Path, rows: List[Dict[str, str]]) -> None:
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

def update_question_status(
    csv_path: Path,
    filename: str,
    status: str,
    model_used: str = "",
    error_msg: str = ""
) -> None:
    rows = read_question_list(csv_path)
    for row in rows:
        if row["filename"] == filename:
            row["status"] = status
            if model_used:
                row["model_used"] = model_used
            if error_msg:
                row["error_msg"] = error_msg
            elif status == STATUS_COMPLETED or status == STATUS_PENDING:
                row["error_msg"] = "" # clear error on success or reset
            break
    write_question_list(csv_path, rows)
