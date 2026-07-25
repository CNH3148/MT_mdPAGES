"""Quick diagnostic script to check the JSON cache for 臨床生理學與病理學."""
import json
from pathlib import Path

data_cache = Path(__file__).resolve().parent.parent.parent / "data_MD_website" / "data_cache"

# Check main questions JSON
q_file = data_cache / "臨床生理學與病理學.json"
print(f"=== Checking: {q_file.name} ===")
print(f"File exists: {q_file.exists()}")
print(f"File size: {q_file.stat().st_size} bytes")

data = json.loads(q_file.read_text(encoding='utf-8'))
print(f"Total entries: {len(data)}")

# Check for missing year
missing_year = [q for q in data if 'year' not in q]
print(f"Entries missing 'year': {len(missing_year)}")
if missing_year:
    for q in missing_year[:5]:
        print(f"  -> source: {q.get('_source_path', '?')}, keys: {list(q.keys())[:10]}")

# Check for non-string year
bad_year = [q for q in data if 'year' in q and not isinstance(q['year'], str)]
print(f"Entries with non-string 'year': {len(bad_year)}")
if bad_year:
    for q in bad_year[:5]:
        print(f"  -> year={q['year']} ({type(q['year']).__name__}), source={q.get('_source_path','?')}")

# Check year distribution
years = {}
for q in data:
    y = q.get('year', '?')
    years[y] = years.get(y, 0) + 1

print(f"\nYear distribution:")
for y in sorted(years.keys()):
    print(f"  {y}: {years[y]} questions")

# Check year parsing compatibility
print("\nYear filter test (110-115):")
for q in data:
    y = q.get('year', '')
    try:
        year_int = int(y.split('-')[0])
    except (ValueError, AttributeError) as e:
        print(f"  PARSE ERROR: year={y!r}, source={q.get('_source_path','?')}, error={e}")

# Check for entries without 'type' field
no_type = [q for q in data if 'type' not in q]
print(f"\nEntries missing 'type': {len(no_type)}")
if no_type:
    for q in no_type[:3]:
        print(f"  -> source: {q.get('_source_path', '?')}, keys: {list(q.keys())[:8]}")

# Check topics JSON
t_file = data_cache / "topics_臨床生理學與病理學.json"
print(f"\n=== Checking: {t_file.name} ===")
print(f"File exists: {t_file.exists()}")
topics_data = json.loads(t_file.read_text(encoding='utf-8'))
print(f"Total topics: {len(topics_data)}")
print(f"Type: {type(topics_data).__name__}")

# Check if topics_data is a dict (expected) or something else
if isinstance(topics_data, dict):
    print("Topics structure: dict (correct)")
    for name in list(topics_data.keys())[:3]:
        print(f"  Topic: {name}")
elif isinstance(topics_data, list):
    print("Topics structure: list (UNEXPECTED - should be dict)")
else:
    print(f"Topics structure: {type(topics_data).__name__} (UNEXPECTED)")
