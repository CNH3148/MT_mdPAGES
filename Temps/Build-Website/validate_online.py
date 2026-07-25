"""Validate the online JSON by downloading and parsing it."""
import json
import urllib.request

subjects = [
    "臨床生理學與病理學",
    "臨床血液學與血庫學",
    "醫學分子檢驗學與臨床鏡檢學",
    "微生物學與臨床微生物學",
    "生物化學與臨床生化學",
    "臨床血清免疫學與臨床病毒學"
]

base_url = "https://cnh3148.github.io/MT_mdPAGES/data_cache/"

for sub in subjects:
    url = base_url + urllib.parse.quote(sub) + ".json"
    print(f"\n=== {sub} ===")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            print(f"  HTTP {resp.status}, Size: {len(raw)} bytes")
            data = json.loads(raw)
            print(f"  Valid JSON: YES, Entries: {len(data)}")
            
            # Check for missing year
            missing_year = [q for q in data if 'year' not in q]
            if missing_year:
                print(f"  WARNING: {len(missing_year)} entries missing 'year'")
                for q in missing_year[:3]:
                    print(f"    source: {q.get('_source_path', '?')}")
            
            # Check year parsing
            for q in data:
                y = q.get('year', '')
                try:
                    int(str(y).split('-')[0])
                except:
                    print(f"  PARSE ERROR: year={y!r}, source={q.get('_source_path','?')}")
                    
    except json.JSONDecodeError as e:
        print(f"  INVALID JSON: {e}")
        # Try to show where the error is
        try:
            text = raw.decode('utf-8')
            pos = e.pos if hasattr(e, 'pos') else -1
            print(f"  Error at position {pos}")
            if pos >= 0:
                start = max(0, pos - 100)
                end = min(len(text), pos + 100)
                print(f"  Context: ...{text[start:end]}...")
        except:
            pass
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")

# Also check topics JSONs
print("\n\n=== TOPICS JSONs ===")
for sub in subjects:
    url = base_url + "topics_" + urllib.parse.quote(sub) + ".json"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            data = json.loads(raw)
            print(f"  topics_{sub}: OK ({len(data)} topics, {len(raw)} bytes)")
    except json.JSONDecodeError as e:
        print(f"  topics_{sub}: INVALID JSON at pos {getattr(e, 'pos', '?')}")
    except Exception as e:
        print(f"  topics_{sub}: ERROR {type(e).__name__}: {e}")
