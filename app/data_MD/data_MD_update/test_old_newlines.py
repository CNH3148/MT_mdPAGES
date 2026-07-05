import os
import glob

search_dir = r"c:\Users\star0\Desktop\data_MD\data_MD_update\old_MD"
for root, dirs, files in os.walk(search_dir):
    for file in files:
        if file.endswith('.md'):
            path = os.path.join(root, file)
            print(f"--- {file} ---")
            content = open(path, 'rb').read()
            text = content.decode('utf-8')
            print(repr(text[:300]))
            break
