from pathlib import Path
from typing import Any
import ruamel.yaml

def update_user_data(filepath: Path, updates: dict[str, Any]) -> bool:
    """
    更新 Markdown 檔案的 YAML frontmatter 內的使用者資料欄位。
    包含: current_answer, bookmarked, tags, is_fixed.
    不會更動其他欄位與 Markdown body，並保留原本 YAML 格式與註解。
    """
    if not filepath.exists():
        return False

    content = filepath.read_text(encoding='utf-8')
    parts = content.split('---\n', 2)
    
    if len(parts) < 3 or parts[0].strip() != '':
        # Invalid markdown file format without proper frontmatter
        return False

    yaml_str = parts[1]
    body = parts[2]

    yaml = ruamel.yaml.YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    try:
        data = yaml.load(yaml_str)
    except Exception as e:
        print(f"YAML load error: {e}")
        return False
        
    if data is None:
        data = {}

    allowed_fields = {'current_answer', 'bookmarked', 'tags', 'is_fixed'}
    changed = False

    for key, value in updates.items():
        if key in allowed_fields:
            if data.get(key) != value:
                data[key] = value
                changed = True

    if not changed:
        return True # Nothing to update

    from io import StringIO
    buf = StringIO()
    yaml.dump(data, buf)
    new_yaml_str = buf.getvalue()

    # Reconstruct the file content
    new_content = f"---\n{new_yaml_str}---\n{body}"
    filepath.write_text(new_content, encoding='utf-8')
    
    return True
