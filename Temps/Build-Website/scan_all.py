"""Scan all MD files to find multi-line question fields that would break YAML parsing."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path('Scripts').resolve()))
from md_engine.parser import parse_question_file

data_md = Path('data_MD')
subjects = [
    "微生物學與臨床微生物學",
    "生物化學與臨床生化學",
    "臨床生理學與病理學",
    "臨床血液學與血庫學",
    "臨床血清免疫學與臨床病毒學",
    "醫學分子檢驗學與臨床鏡檢學",
]

all_errors = []
total_files = 0

for sub in subjects:
    sub_dir = data_md / sub
    for root, dirs, files in __import__('os').walk(sub_dir):
        if '_topics' in root:
            continue
        for f in files:
            if f.endswith('.md'):
                total_files += 1
                fp = Path(root) / f
                result = parse_question_file(fp)
                if result and not result.get('year'):
                    all_errors.append((fp.relative_to(data_md).as_posix(), list(result.keys())[:6]))

print(f"Total MD files scanned: {total_files}")
print(f"Files with missing 'year' after parse: {len(all_errors)}")
for path, keys in all_errors:
    print(f"  ⚠️ {path}  (keys: {keys})")
