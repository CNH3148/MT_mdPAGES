import argparse
import logging
import sys
from pathlib import Path
from typing import List, Dict

from _utils import (
    DATA_ROOT,
    CSV_FILENAME,
    SUBJECTS,
    parse_frontmatter,
    has_explanation,
    read_question_list,
    write_question_list,
    STATUS_PENDING,
    STATUS_SKIPPED,
    STATUS_COMPLETED,
    logger
)

def parse_year_sort_key(year_str: str) -> tuple:
    """Parse year string (e.g. 115-1) into a sortable tuple (-115, -1)."""
    parts = year_str.split('-')
    try:
        y = int(parts[0])
        sem = int(parts[1]) if len(parts) > 1 else 0
        return (-y, -sem)
    except ValueError:
        return (0, 0)

def generate_list():
    csv_path = Path(__file__).resolve().parent / CSV_FILENAME
    
    # Read existing
    existing_rows = read_question_list(csv_path)
    existing_status = {row["filename"]: row["status"] for row in existing_rows}
    
    new_rows: List[Dict[str, str]] = []
    
    logger.info(f"Scanning data root: {DATA_ROOT}")
    
    scanned_count = 0
    
    for subject in SUBJECTS:
        subj_dir = DATA_ROOT / subject
        if not subj_dir.is_dir():
            logger.warning(f"Subject directory not found: {subj_dir}")
            continue
            
        for year_dir in subj_dir.iterdir():
            if not year_dir.is_dir():
                continue
            
            year_str = year_dir.name
            
            for md_file in year_dir.glob("*.md"):
                if md_file.name == "_report.txt" or not md_file.name[0].isdigit():
                    continue
                    
                filename = md_file.name
                
                # e.g., 5_115-1_1.md
                # parts: exam_id, year, qnum
                name_no_ext = filename[:-3]
                parts = name_no_ext.split('_')
                if len(parts) != 3:
                    continue
                    
                exam_id = parts[0]
                qnum = parts[2]
                
                try:
                    qnum_int = int(qnum)
                    exam_id_int = int(exam_id)
                except ValueError:
                    continue
                
                scanned_count += 1
                
                try:
                    metadata, body = parse_frontmatter(md_file)
                except Exception as e:
                    logger.error(f"Failed to parse {filename}: {e}")
                    continue
                    
                difficulty = metadata.get("difficulty", "適中")
                
                status = STATUS_PENDING
                
                # Check if it already has explanation
                if has_explanation(body):
                    status = STATUS_SKIPPED
                
                # If it exists in CSV and is already Completed or Skipped, preserve that status
                # unless we just found it to be Skipped
                if filename in existing_status:
                    old_status = existing_status[filename]
                    if old_status in (STATUS_COMPLETED, STATUS_SKIPPED):
                        status = old_status
                        
                rel_path = f"{subject}/{year_str}/{filename}"
                
                row = {
                    "filename": filename,
                    "subject": subject,
                    "year": year_str,
                    "exam_id": exam_id,
                    "question_number": qnum,
                    "difficulty": difficulty,
                    "relative_path": rel_path,
                    "status": status,
                    "model_used": "",
                    "error_msg": ""
                }
                
                new_rows.append((parse_year_sort_key(year_str), exam_id_int, qnum_int, row))

    # Sort
    new_rows.sort(key=lambda x: (x[0], x[1], x[2]))
    
    final_rows = [x[3] for x in new_rows]
    
    write_question_list(csv_path, final_rows)
    
    stats = {
        STATUS_PENDING: 0,
        STATUS_COMPLETED: 0,
        STATUS_SKIPPED: 0,
        "Total": len(final_rows)
    }
    for r in final_rows:
        if r["status"] == STATUS_PENDING: stats[STATUS_PENDING] += 1
        elif r["status"] == STATUS_COMPLETED: stats[STATUS_COMPLETED] += 1
        elif r["status"] == STATUS_SKIPPED: stats[STATUS_SKIPPED] += 1
        
    logger.info(f"Scanned {scanned_count} matching files.")
    logger.info(f"Generated CSV with {stats['Total']} rows. Pending: {stats[STATUS_PENDING]}, Completed: {stats[STATUS_COMPLETED]}, Skipped: {stats[STATUS_SKIPPED]}")


if __name__ == "__main__":
    generate_list()
