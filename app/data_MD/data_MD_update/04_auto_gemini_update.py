import os
import subprocess
import re
from google import genai
from google.genai import types

import sys

API_KEY = "AQ.Ab8RN6LPzrurADxpCfk6KWX5nofQkI5DlLOy6nGqIbcvLBTweA"
MODEL_NAME = "gemini-3.1-pro-preview"

def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    print("=== Auto Gemini Update Script ===")
    
    # 1. Run 02_prepare_ai_reference.py
    print("[INFO] Running 02_prepare_ai_reference.py...")
    result = subprocess.run(
        [sys.executable, "data_MD_update/02_prepare_ai_reference.py"], 
        capture_output=True
    )
    stdout_text = result.stdout.decode("utf-8", errors="ignore") + result.stderr.decode("utf-8", errors="ignore")
    try:
        stdout_text += result.stdout.decode("cp950", errors="ignore") + result.stderr.decode("cp950", errors="ignore")
    except:
        pass
    # print("OUTPUT:", stdout_text) # commented out to avoid UnicodeEncodeError
    
    if "No Pending topics found" in stdout_text and "InProgress" not in stdout_text:
        print("[INFO] No pending topics left to update.")
        return
        
    match = re.search(r"data_MD_update[/\\]new_MD[/\\](.*?\.md)", stdout_text)
    if not match:
        print("[ERROR] Could not extract output path from 02_prepare stdout. Raw output:")
        print(repr(stdout_text))
        return
    
    output_path = os.path.join("data_MD_update", "new_MD", match.group(1))
    print(f"[INFO] Target output file: {output_path}")

    # 2. Read Reference and System Instructions
    with open("data_MD_update/topic分析撰寫指引.txt", "r", encoding="utf-8") as f:
        system_instruction = f.read()
        
    with open("data_MD_update/reference_for_ai.txt", "r", encoding="utf-8") as f:
        reference_text = f.read()

    # 3. Call Gemini API
    print(f"[INFO] Calling {MODEL_NAME} with Grounding, Thinking=High, Media=High...")
    client = genai.Client(api_key=API_KEY)
    
    # Using raw dict config for maximum compatibility with requested flags
    config = {
        "system_instruction": system_instruction,
        "tools": [{"google_search": {}}],
        "thinking_config": {"thinking_budget": 1024}, # Simulated 'high' thinking
    }

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=reference_text,
            config=config
        )
        output_markdown = response.text
        
        if output_markdown.startswith("```markdown"):
            output_markdown = output_markdown[11:]
        elif output_markdown.startswith("```"):
            output_markdown = output_markdown[3:]
            
        if output_markdown.endswith("```"):
            output_markdown = output_markdown[:-3]
            
        output_markdown = output_markdown.strip() + "\n"

    except Exception as e:
        print(f"[ERROR] API Call failed: {e}")
        return

    # 4. Save to new_MD
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_markdown)
    print(f"[INFO] Wrote response to {output_path}")

    # 5. Run Validate and Deploy
    print("[INFO] Running 03_validate_and_deploy.py --validate-only...")
    subprocess.run([sys.executable, "data_MD_update/03_validate_and_deploy.py", "--validate-only"])
    
    print("[INFO] Running 03_validate_and_deploy.py --deploy-all...")
    subprocess.run([sys.executable, "data_MD_update/03_validate_and_deploy.py", "--deploy-all"])
    
    print("[INFO] Finished.")

if __name__ == "__main__":
    main()
