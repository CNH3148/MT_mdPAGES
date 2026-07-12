import os
from pathlib import Path
import re

def fix_file(path: Path):
    try:
        content = path.read_bytes()
        text = content.decode('utf-8')
    except Exception as e:
        print(f"Error reading {path}: {e}")
        return

    # 統一將 \r 洗掉，以 \n 為基準判斷
    text_lf = text.replace('\r', '')
    
    # 判斷是否為「雙倍換行 Bug」的受災戶：
    # 正常的 YAML 前言：
    # type: topic
    # subject: ...
    # 受災戶的 YAML 前言：
    # type: topic
    # 
    # subject: ...
    if 'type: topic\n\nsubject:' in text_lf or 'type: topic\n\n\nsubject:' in text_lf:
        print(f"[FIXING] {path.name}")
        # 將所有的 \n\n 壓縮成 \n
        fixed_text = text_lf.replace('\n\n', '\n')
        
        # 寫回檔案 (Windows 預設會再轉回 \r\n，但數量是正確的單倍了！)
        path.write_text(fixed_text, encoding='utf-8')
        print(f"  -> Fixed.")
    else:
        # 沒中標，不用處理
        pass

def main():
    root_dirs = [
        Path(r"c:\Users\star0\Desktop\data_MD"),
        Path(r"c:\Users\star0\Desktop\data_MD\data_MD_update\new_MD")
    ]
    
    for r in root_dirs:
        for root, dirs, files in os.walk(r):
            # 不要進到 old_MD 或其他不相干的資料夾
            if 'old_MD' in root or '.git' in root or '.obsidian' in root:
                continue
                
            for file in files:
                if file.endswith(".md"):
                    p = Path(root) / file
                    fix_file(p)

if __name__ == "__main__":
    main()
