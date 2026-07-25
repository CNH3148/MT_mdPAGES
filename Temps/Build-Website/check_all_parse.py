"""Check all subjects for YAML parse errors in 115-2 files."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path('Scripts').resolve()))
from md_engine.parser import parse_question_file

data_md = Path('data_MD')

subjects = [d for d in data_md.iterdir() if d.is_dir() and not d.name.startswith('_') and not d.name.startswith('.')]

for subject_dir in sorted(subjects):
    if not (subject_dir / '115-2').exists():
        continue
    
    print(f"\n=== {subject_dir.name} / 115-2 ===")
    exam_dir = subject_dir / '115-2'
    md_files = sorted(exam_dir.glob('*.md'))
    print(f"  Total files: {len(md_files)}")
    
    parse_errors = []
    for f in md_files:
        result = parse_question_file(f)
        if not result.get('year') or not result.get('no'):
            parse_errors.append((f.name, result.get('year', 'MISSING'), result.get('no', 'MISSING'), list(result.keys())[:5]))
    
    if parse_errors:
        print(f"  ⚠️ PARSE ERRORS ({len(parse_errors)}):")
        for fname, year, no, keys in parse_errors:
            print(f"    {fname}: year={year!r}, no={no!r}, keys={keys}")
    else:
        print(f"  ✅ All files parsed correctly")
