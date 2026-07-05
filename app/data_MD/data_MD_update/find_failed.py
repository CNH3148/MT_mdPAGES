import os
import glob
for root, dirs, files in os.walk('data_MD_update'):
    for f in files:
        if '固態腫瘤分子病理學' in f and f.endswith('.md'):
            path = os.path.join(root, f)
            print(f"--- {path} ---")
            content = open(path, 'rb').read()
            print(content[-500:].decode('utf-8', errors='ignore'))
            print("=================")
