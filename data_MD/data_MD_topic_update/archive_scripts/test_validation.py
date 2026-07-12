import sys
import os
from pathlib import Path

data_md_update_path = Path(r"C:\Users\star0\Desktop\data_MD\data_MD_update")
sys.path.insert(0, str(data_md_update_path))

import importlib.util
spec = importlib.util.spec_from_file_location("validate", data_md_update_path / "03_validate_and_deploy.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
validate_topic = module.validate_topic

new_file = data_md_update_path / "new_MD" / "醫學分子檢驗學與臨床鏡檢學" / "固態腫瘤分子病理學.md"
old_file = data_md_update_path / "old_MD" / "醫學分子檢驗學與臨床鏡檢學" / "固態腫瘤分子病理學.md"
topic_name = "固態腫瘤分子病理學"

print(f"Checking if new_file exists: {new_file.exists()}")
print(f"Checking if old_file exists: {old_file.exists()}")

errors = validate_topic(new_file, old_file, topic_name)
print("Errors:", errors)
