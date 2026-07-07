import os
import shutil
import logging
from pathlib import Path

from _utils import (
    DATA_ROOT,
    OLD_TEMP_DIR,
    NEW_TEMP_DIR,
    parse_frontmatter,
    logger
)

import re

def format_explanation_markdown(raw_response: str) -> str:
    """
    Format the response for insertion.
    - Replace <br><br> with <br>
    - Ensure it does not have outer markdown code block wrappers
    - Add leading newlines
    """
    # Normalize line endings from Windows clipboard
    raw_response = raw_response.replace('\r\n', '\n').replace('\r', '\n')
    # Clean up <br> tags with surrounding whitespaces/newlines, which could break markdown tables
    formatted = re.sub(r'\s*<br>\s*', '<br>', raw_response)
    formatted = re.sub(r'(<br>)+', '<br>', formatted)
    
    # Remove empty lines between markdown table rows (i.e. between | and |)
    formatted = re.sub(r'\|[ \t]*\n[\n\s]*\|', '|\n|', formatted)
    
    # Strip potential ```markdown ... ```
    if formatted.startswith("```markdown"):
        formatted = formatted[11:]
        if formatted.endswith("```"):
            formatted = formatted[:-3]
    elif formatted.startswith("```"):
        # Could be other codeblock
        first_newline = formatted.find("\n")
        if first_newline != -1 and first_newline < 20:
            formatted = formatted[first_newline+1:]
        if formatted.endswith("```"):
            formatted = formatted[:-3]

    formatted = formatted.strip()
    return f"\n\n{formatted}\n"

def run_validation(relative_path: str, explanation_content: str) -> tuple[bool, str]:
    """
    Validation logic.
    Returns (is_valid, error_msg)
    """
    source_file = DATA_ROOT / relative_path
    if not source_file.exists():
        return False, f"Source file not found: {source_file}"

    filename = source_file.name
    old_file = OLD_TEMP_DIR / filename
    new_file = NEW_TEMP_DIR / filename
    
    # Ensure temp dirs exist
    OLD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    NEW_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Copy to old_temp
    shutil.copy2(source_file, old_file)

    # 2. Prepare new_temp
    with open(source_file, "r", encoding="utf-8") as f:
        original_content = f.read()

    # Append explanation
    if "## 筆記與詳解" not in original_content:
        return False, "CHECK-0: Missing '## 筆記與詳解' section in original file"

    parts = original_content.split("## 筆記與詳解")
    new_content = parts[0] + "## 筆記與詳解" + format_explanation_markdown(explanation_content)

    with open(new_file, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Re-read to ensure we are testing what's on disk
    with open(old_file, "r", encoding="utf-8") as f:
        old_text = f.read()
    with open(new_file, "r", encoding="utf-8") as f:
        new_text = f.read()

    # CHECK-1: Text before '## 筆記與詳解' must be identical
    old_pre = old_text.split("## 筆記與詳解")[0]
    new_pre = new_text.split("## 筆記與詳解")[0]
    if old_pre != new_pre:
        return False, "CHECK-1: Text before '## 筆記與詳解' was modified"

    # CHECK-2: No <br><br>
    if "<br><br>" in new_text.split("## 筆記與詳解")[1]:
        return False, "CHECK-2: Found <br><br> in explanation"

    # CHECK-3: Size increased by at least 100 chars
    if len(new_text) - len(old_text) < 100:
        return False, "CHECK-3: New file size did not increase by at least 100 chars"

    # CHECK-4: Explanation has content
    expl_part = new_text.split("## 筆記與詳解")[1].strip()
    if not expl_part:
        return False, "CHECK-4: Explanation is empty"

    # CHECK-5: YAML frontmatter remains identical
    try:
        old_meta, _ = parse_frontmatter(old_file)
        new_meta, _ = parse_frontmatter(new_file)
    except Exception as e:
        return False, f"CHECK-5: YAML frontmatter parsing failed: {e}"
        
    if old_meta != new_meta:
        return False, "CHECK-5: YAML frontmatter was modified"

    # All checks passed! Deploy.
    shutil.copy2(new_file, source_file)
    
    # Clean up temp
    try:
        os.remove(old_file)
        os.remove(new_file)
    except OSError:
        pass # ignore cleanup errors

    return True, ""
