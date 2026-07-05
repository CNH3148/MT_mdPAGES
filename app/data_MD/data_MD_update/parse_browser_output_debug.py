import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import os
import traceback

input_path = "C:/Users/star0/.gemini/antigravity/brain/699df4e3-d0f4-4b38-aa46-02bf2f3a6dfe/.system_generated/steps/112/output.txt"
output_path = "C:/Users/star0/Desktop/data_MD/data_MD_update/new_MD/dumps/分子生物學核心原理.md"

try:
    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    json_str = ""
    in_json = False
    for line in lines:
        if line.strip() == "```json":
            in_json = True
            continue
        if line.strip() == "```" and in_json:
            break
        if in_json:
            json_str += line

    if not json_str.strip():
        print("ERROR: No JSON string found in the file.")
    else:
        text = json.loads(json_str)
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        print("Extraction successful.")
except Exception as e:
    print(f"Error occurred:\n{traceback.format_exc()}")
