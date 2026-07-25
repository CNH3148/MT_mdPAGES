"""Simulate what parse_question_file does when YAML parse fails."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path('Scripts').resolve()))
from md_engine.parser import parse_question_file

# Test with the problematic file
result = parse_question_file(Path(r'data_MD/臨床生理學與病理學/115-2/1_115-2_28.md'))
print(f"Result type: {type(result).__name__}")
print(f"Result bool: {bool(result)}")
print(f"Result keys: {list(result.keys())}")
print(f"year: {result.get('year', 'MISSING')!r}")
print(f"no: {result.get('no', 'MISSING')!r}")
print(f"subject: {result.get('subject', 'MISSING')!r}")
print(f"Full result (truncated): {str(result)[:500]}")
