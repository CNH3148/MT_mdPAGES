from typing import Any
from pathlib import Path
import ruamel.yaml

def parse_question_file(filepath: Path) -> dict[str, Any]:
    """
    解析題目 .md 檔案，回傳結構化 dict。
    將 yaml 中的 'question_number' 轉換回 'no' 以相容前端。
    並提取 Markdown Body 為 'explanation'。
    """
    if not filepath.exists():
        return {}

    content = filepath.read_text(encoding='utf-8')
    parts = content.split('---\n', 2)
    
    yaml = ruamel.yaml.YAML(typ='safe')
    yaml_data = {}
    
    if len(parts) >= 3 and parts[0].strip() == '':
        try:
            yaml_data = yaml.load(parts[1]) or {}
        except Exception:
            yaml_data = {}
        body = parts[2]
    else:
        body = content
        
    # Mapping question_number to no for frontend compatibility
    if 'question_number' in yaml_data:
        yaml_data['no'] = yaml_data.pop('question_number')
        
    # Extract topic name from [[Name]]
    if 'topic' in yaml_data and isinstance(yaml_data['topic'], str):
        t = yaml_data['topic']
        if t.startswith('[[') and t.endswith(']]'):
            t = t[2:-2]
        yaml_data['topic'] = t
        
    # Resolve image urls
    if 'images' in yaml_data and isinstance(yaml_data['images'], list):
        resolved = []
        for img in yaml_data['images']:
            if img.startswith('http'):
                resolved.append(img)
            else:
                resolved.append(f"/attachments/{img}")
        yaml_data['images'] = resolved
        
    # Set default values for user state if missing
    yaml_data.setdefault('current_answer', '')
    yaml_data.setdefault('is_fixed', None)
    yaml_data.setdefault('bookmarked', False)
    yaml_data.setdefault('tags', [])
    
    # Ensure no is integer
    if 'no' in yaml_data and yaml_data['no'] is not None:
        try:
            yaml_data['no'] = int(yaml_data['no'])
        except ValueError:
            pass
            
    # Ensure exam_id is string
    if 'exam_id' in yaml_data:
        yaml_data['exam_id'] = str(yaml_data['exam_id'])

    # Extract explanation (everything below '## 筆記與詳解')
    explanation = ""
    if "## 筆記與詳解" in body:
        explanation = body.split("## 筆記與詳解", 1)[1].strip()
        
    yaml_data['explanation'] = explanation
    
    # QID
    if 'year' in yaml_data and 'exam_id' in yaml_data and 'no' in yaml_data:
        yaml_data['qid'] = f"{yaml_data['year']}_{yaml_data['exam_id']}_{yaml_data['no']}"

    return yaml_data

def parse_topic_file(filepath: Path) -> dict[str, Any]:
    """
    解析主題 .md 檔案。
    """
    if not filepath.exists():
        return {}

    content = filepath.read_text(encoding='utf-8')
    parts = content.split('---\n', 2)
    
    yaml = ruamel.yaml.YAML(typ='safe')
    yaml_data = {}
    
    if len(parts) >= 3 and parts[0].strip() == '':
        try:
            yaml_data = yaml.load(parts[1]) or {}
        except Exception:
            yaml_data = {}
        body = parts[2]
    else:
        body = content
        
    yaml_data.setdefault('is_pinned', False)
    yaml_data.setdefault('aliases', [])
    
    # Return the entire body as the summary markdown
    yaml_data['summary_markdown'] = body.strip()
    
    # Add name based on filename if not present
    if 'name' not in yaml_data:
        yaml_data['name'] = filepath.stem

    return yaml_data
