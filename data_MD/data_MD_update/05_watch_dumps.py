import os
import sys
import time
import shutil
import subprocess
import csv

DUMPS_DIR = os.path.join("data_MD_update", "new_MD", "dumps")
CSV_PATH = os.path.join("data_MD_update", "topic_list.csv")

def get_topic_subject_map() -> dict:
    """Read CSV and build mapping of topic_name -> subject, prioritizing InProgress"""
    priority = {"InProgress": 4, "Failed": 3, "Pending": 2, "Validated": 1, "Completed": 0}
    mapping = {}
    current_priorities = {}
    if not os.path.exists("data_MD_update/topic_list.csv"):
        return mapping
        
    with open("data_MD_update/topic_list.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            topic_name = row["TopicName"]
            status = row.get("Status", "Pending")
            p = priority.get(status, -1)
            
            if topic_name not in mapping or p > current_priorities[topic_name]:
                mapping[topic_name] = row["Subject"]
                current_priorities[topic_name] = p
    return mapping

def check_topic_status(topic_name: str) -> tuple[str, str]:
    """Check the Status and Note of a specific topic in the CSV."""
    if not os.path.exists("data_MD_update/topic_list.csv"):
        return "", ""
        
    with open("data_MD_update/topic_list.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["TopicName"] == topic_name:
                return row["Status"], row.get("Note", "")
    return "", ""

def main():
    os.makedirs(DUMPS_DIR, exist_ok=True)
    print(f"[INFO] Watching for new .md files in: {DUMPS_DIR}")
    print("[INFO] Press Ctrl+C to stop.")
    
    while True:
        try:
            time.sleep(3)
            files = [f for f in os.listdir(DUMPS_DIR) if f.endswith(".md")]
            if not files:
                continue
            
            mapping = get_topic_subject_map()
            
            for file in files:
                topic_name = file[:-3] # remove .md
                subject = mapping.get(topic_name)
                
                if not subject:
                    print(f"[WARNING] Could not find subject for topic: {topic_name}. Skipping.")
                    continue
                
                source_path = os.path.join(DUMPS_DIR, file)
                target_dir = os.path.join("data_MD_update", "new_MD", subject)
                target_path = os.path.join(target_dir, file)
                
                os.makedirs(target_dir, exist_ok=True)
                shutil.move(source_path, target_path)
                print(f"[INFO] Moved '{file}' to {target_path}")
                
                print("[INFO] Running 03_validate_and_deploy.py --validate-only...")
                subprocess.run([sys.executable, "data_MD_update/03_validate_and_deploy.py", "--validate-only", "--topic", topic_name])
                
                print("[INFO] Running 03_validate_and_deploy.py --deploy-all...")
                subprocess.run([sys.executable, "data_MD_update/03_validate_and_deploy.py", "--deploy-all"])
                
                # 檢查這個 Topic 的驗證狀態
                status, note = check_topic_status(topic_name)
                if status == "Failed":
                    print(f"[WARNING] 驗證失敗: {note}")
                    # 生成 Fix Prompt
                    fix_prompt = (
                        "[FIX_PROMPT]\n"
                        f"Topic 名稱: {topic_name}\n\n"
                        "上一次輸出的 Markdown 檔案未能通過嚴格的系統驗證。\n"
                        "請針對以下錯誤原因進行修正，並重新輸出「完整」的 Markdown 檔案（包含所有的 YAML 屬性、分析內容與 Dataview 區塊）：\n\n"
                        f"錯誤原因：\n{note}\n"
                    )
                    # 覆寫 reference_for_ai.txt
                    with open("data_MD_update/reference_for_ai.txt", "w", encoding="utf-8") as f:
                        f.write(fix_prompt)
                    print(f"[INFO] 已產出 [FIX_PROMPT]，等待 06_auto_chrome 原地修正...")
                else:
                    print("[INFO] 驗證成功，準備下一題...")
                    print("[INFO] Running 02_prepare_ai_reference.py for the next topic...")
                    subprocess.run([sys.executable, "data_MD_update/02_prepare_ai_reference.py"])
                
                print(f"[INFO] Done processing {file}. Waiting for next action...\n")
                
        except KeyboardInterrupt:
            print("\n[INFO] Stopping watcher.")
            break
        except Exception as e:
            print(f"[ERROR] An error occurred: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
