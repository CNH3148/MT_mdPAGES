import os
import json
import time
from pathlib import Path
from typing import Any
from .parser import parse_question_file, parse_topic_file

def build_cache(data_md_dir: Path, output_dir: Path):
    """
    掃描 data_MD 目錄下的所有 Markdown 檔案，建立 JSON 格式的快取。
    具有增量更新機制：僅解析有被修改的檔案，跳過未修改的檔案。
    """
    if not data_md_dir.exists():
        print(f"Directory {data_md_dir} does not exist.")
        return
        
    output_dir.mkdir(parents=True, exist_ok=True)
    
    start_time = time.time()
    total_parsed = 0
    total_skipped = 0
    
    subject_dirs = [d for d in data_md_dir.iterdir() if d.is_dir() and not d.name.startswith('_') and not d.name.startswith('.')]
    
    for subject_dir in subject_dirs:
        subject = subject_dir.name
        
        # 1. 讀取舊快取 (Questions)
        q_out_file = output_dir / f"{subject}.json"
        old_questions_dict = {}
        if q_out_file.exists():
            try:
                old_data = json.loads(q_out_file.read_text('utf-8'))
                if isinstance(old_data, list):
                    old_questions_dict = {q.get('_source_path'): q for q in old_data if q.get('_source_path')}
            except Exception:
                print(f"[Warning] Failed to parse existing {q_out_file.name}, will rebuild fully.")
                
        # 2. 讀取舊快取 (Topics)
        topics_out_file = output_dir / f"topics_{subject}.json"
        old_topics_dict = {}
        if topics_out_file.exists():
            try:
                old_topics_dict = json.loads(topics_out_file.read_text('utf-8'))
            except Exception:
                print(f"[Warning] Failed to parse existing {topics_out_file.name}, will rebuild fully.")
                
        questions = []
        topics_dict = {}
        
        # 解析 _topics 裡的主題
        topics_dir = subject_dir / "_topics"
        if topics_dir.exists():
            for topic_file in topics_dir.glob("*.md"):
                source_path = topic_file.relative_to(data_md_dir).as_posix()
                current_mtime = topic_file.stat().st_mtime
                topic_name = topic_file.stem
                
                # Check if we can skip
                old_topic = old_topics_dict.get(topic_name)
                if old_topic and old_topic.get('_source_path') == source_path and old_topic.get('_mtime', 0) >= current_mtime:
                    topics_dict[topic_name] = old_topic
                    total_skipped += 1
                else:
                    topic_data = parse_topic_file(topic_file)
                    topic_data['_source_path'] = source_path
                    topic_data['_mtime'] = current_mtime
                    topics_dict[topic_data['name']] = topic_data
                    total_parsed += 1
                
        # 解析題目
        for root, dirs, files in os.walk(subject_dir):
            if "_topics" in root or "_attachments" in root:
                continue
            for file in files:
                if file.endswith(".md"):
                    filepath = Path(root) / file
                    source_path = filepath.relative_to(data_md_dir).as_posix()
                    current_mtime = filepath.stat().st_mtime
                    
                    old_q = old_questions_dict.get(source_path)
                    if old_q and old_q.get('_mtime', 0) >= current_mtime:
                        questions.append(old_q)
                        total_skipped += 1
                    else:
                        q_data = parse_question_file(filepath)
                        if q_data:
                            q_data['_source_path'] = source_path
                            q_data['_mtime'] = current_mtime
                            questions.append(q_data)
                            total_parsed += 1
                        
        # 排序題目 (根據年份遞減, 題號遞增)
        def sort_key(x):
            return (x.get('year', ''), -x.get('no', 0))
            
        questions.sort(key=sort_key, reverse=True)
        
        # 寫出 [科目].json
        q_out_file.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding='utf-8')
        
        # 寫出 topics_[科目].json
        topics_out_file.write_text(json.dumps(topics_dict, ensure_ascii=False, indent=2), encoding='utf-8')
        
    duration = time.time() - start_time
    print(f"Cache built in {duration:.2f}s (skipped {total_skipped} files, parsed {total_parsed} changed files)")

def update_single_file_cache(filepath: Path, data_md_dir: Path, output_dir: Path):
    """
    當 watchdog 偵測到單一檔案修改或刪除時，局部更新對應的快取，避免全量掃描。
    """
    try:
        relative = filepath.relative_to(data_md_dir)
        subject = relative.parts[0]
        
        if subject.startswith('_') or subject.startswith('.'):
            return
            
        source_path = relative.as_posix()
        is_topic = "_topics" in relative.parts
        file_exists = filepath.exists()
        
        if is_topic:
            topics_out_file = output_dir / f"topics_{subject}.json"
            topics_dict = {}
            if topics_out_file.exists():
                try:
                    topics_dict = json.loads(topics_out_file.read_text('utf-8'))
                except Exception:
                    pass
            
            topic_name = filepath.stem
            
            if not file_exists:
                # 刪除事件
                if topic_name in topics_dict:
                    del topics_dict[topic_name]
                    print(f"[Cache Update] Removed topic {topic_name}")
            else:
                # 新增/修改事件
                topic_data = parse_topic_file(filepath)
                topic_data['_source_path'] = source_path
                topic_data['_mtime'] = filepath.stat().st_mtime
                topics_dict[topic_data['name']] = topic_data
                print(f"[Cache Update] Updated topic {topic_name}")
                
            topics_out_file.write_text(json.dumps(topics_dict, ensure_ascii=False, indent=2), encoding='utf-8')
            
        else:
            q_out_file = output_dir / f"{subject}.json"
            questions = []
            if q_out_file.exists():
                try:
                    questions = json.loads(q_out_file.read_text('utf-8'))
                except Exception:
                    pass
            
            if not file_exists:
                # 刪除事件
                original_len = len(questions)
                questions = [q for q in questions if q.get('_source_path') != source_path]
                if len(questions) < original_len:
                    print(f"[Cache Update] Removed question {filepath.name}")
            else:
                # 新增/修改事件
                q_data = parse_question_file(filepath)
                if q_data:
                    q_data['_source_path'] = source_path
                    q_data['_mtime'] = filepath.stat().st_mtime
                    
                    # 替換或新增
                    found = False
                    for i, q in enumerate(questions):
                        if q.get('_source_path') == source_path:
                            questions[i] = q_data
                            found = True
                            break
                    if not found:
                        questions.append(q_data)
                    print(f"[Cache Update] Updated question {filepath.name}")
            
            # 重新排序
            def sort_key(x):
                return (x.get('year', ''), -x.get('no', 0))
            questions.sort(key=sort_key, reverse=True)
            
            q_out_file.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding='utf-8')
            
    except ValueError:
        # File not in data_md_dir
        pass
    except Exception as e:
        print(f"[Cache Update Error] {e}")
