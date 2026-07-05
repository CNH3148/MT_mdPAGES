import os
import sys
import subprocess
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from md_engine.cache_builder import build_cache
from md_engine.watcher import start_watcher
from md_engine.writer import update_user_data

BASE_DIR = Path(__file__).parent.resolve()

# Ensure directories exist
os.makedirs(BASE_DIR / "data_MD/_attachments", exist_ok=True)
os.makedirs(BASE_DIR / "data_cache", exist_ok=True)
os.makedirs(BASE_DIR / "saves", exist_ok=True)
os.makedirs(BASE_DIR / "data", exist_ok=True)

# Build cache and start watchdog on startup
data_md_path = BASE_DIR / "data_MD"
data_cache_path = BASE_DIR / "data_cache"

print("Building Markdown cache...")
build_cache(data_md_path, data_cache_path)
watcher_observer = start_watcher(data_md_path, data_cache_path)

app = FastAPI()

# Prevent browser caching of static assets so updates are always served fresh
from fastapi import Request
from fastapi.responses import Response

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith(('.js', '.css', '.html', '.json')) or path == '/':
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Serve data files from cache instead of old data folder
app.mount("/data_cache", StaticFiles(directory="data_cache"), name="data_cache")

# Serve attachments for images in Markdown
app.mount("/attachments", StaticFiles(directory="data_MD/_attachments"), name="attachments")

# ==========================================
# Legacy Saves API (To be deprecated in frontend)
# ==========================================
@app.post("/api/save_progress/{slot}")
def save_progress(slot: int, data: dict):
    save_path = os.path.join("saves", f"save_slot_{slot}.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"status": "success"}

@app.post("/api/open_saves_folder")
def open_saves_folder():
    saves_dir = os.path.abspath("saves")
    try:
        if sys.platform == 'win32':
            os.startfile(saves_dir)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', saves_dir])
        else:
            subprocess.Popen(['xdg-open', saves_dir])
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/load_progress/{slot}")
def load_progress(slot: int):
    save_path = os.path.join("saves", f"save_slot_{slot}.json")
    if os.path.exists(save_path):
        with open(save_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {}

@app.delete("/api/delete_progress/{slot}")
def delete_progress(slot: int):
    save_path = os.path.join("saves", f"save_slot_{slot}.json")
    if os.path.exists(save_path):
        os.remove(save_path)
    return {"status": "success"}

@app.get("/api/slots")
def get_slots():
    # Deprecated
    return {"status": "ok", "data": []}

@app.get("/api/cache_version")
def get_cache_version():
    try:
        if data_cache_path.exists():
            max_mtime = 0
            for f in data_cache_path.glob("*.json"):
                mtime = f.stat().st_mtime
                if mtime > max_mtime:
                    max_mtime = mtime
            return {"version": max_mtime}
    except Exception as e:
        pass
    return {"version": 0}

@app.get("/api/slot_names")
def get_slot_names():
    names = {}
    for i in range(1, 4):
        save_path = os.path.join("saves", f"save_slot_{i}.json")
        if os.path.exists(save_path):
            try:
                with open(save_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    if "_meta" in data and "slotName" in data["_meta"]:
                        names[str(i)] = data["_meta"]["slotName"]
            except Exception:
                pass
    return names

class RenameSlotRequest(BaseModel):
    name: str

@app.post("/api/rename_slot/{slot}")
def rename_slot(slot: int, req: RenameSlotRequest):
    save_path = os.path.join("saves", f"save_slot_{slot}.json")
    data = {}
    if os.path.exists(save_path):
        with open(save_path, "r", encoding="utf-8-sig") as f:
            try:
                data = json.load(f)
            except Exception:
                pass
                
    if "_meta" not in data:
        data["_meta"] = {}
    data["_meta"]["slotName"] = req.name
    
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"status": "success"}

class SearchRule(BaseModel):
    name: str
    query: str

@app.post("/api/save_search_rule")
def save_search_rule(rule: SearchRule):
    rules_path = os.path.join("data_cache", "saved_searches.json")
    rules = []
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8-sig") as f:
            rules = json.load(f)
            
    for r in rules:
        if r["name"] == rule.name:
            r["query"] = rule.query
            break
    else:
        rules.append({"name": rule.name, "query": rule.query})
        
    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    return {"status": "success"}

@app.get("/api/get_search_rules")
def get_search_rules():
    rules_path = os.path.join("data_cache", "saved_searches.json")
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return []

@app.delete("/api/delete_search_rule/{rule_name}")
def delete_search_rule(rule_name: str):
    rules_path = os.path.join("data_cache", "saved_searches.json")
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8-sig") as f:
            rules = json.load(f)
        rules = [r for r in rules if r['name'] != rule_name]
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
    return {"status": "success"}

# ==========================================
# Question Update APIs (Modified to update Markdown)
# ==========================================
class QuestionPatch(BaseModel):
    current_answer: str = None
    is_fixed: bool = None
    bookmarked: bool = None
    answer: str = None

@app.patch("/api/q/{subject}/{qid}")
def patch_question(subject: str, qid: str, patch: QuestionPatch):
    # Parse qid format: {year}_{exam_id}_{no}
    parts = qid.split('_')
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Invalid QID format")
        
    year, exam_id, no = parts
    
    md_path = data_md_path / subject / year / f"{exam_id}_{year}_{no}.md"
    
    if not md_path.exists():
        raise HTTPException(status_code=404, detail=f"Markdown file not found: {md_path}")
        
    updates = {}
    if patch.current_answer is not None:
        updates['current_answer'] = patch.current_answer
    if patch.is_fixed is not None:
        updates['is_fixed'] = patch.is_fixed
    if patch.bookmarked is not None:
        updates['bookmarked'] = patch.bookmarked
    if patch.answer is not None:
        updates['answer'] = patch.answer
        
    if not updates:
        return {"status": "success"}
        
    success = update_user_data(md_path, updates)
    if success:
        return {"status": "success"}
    return {"status": "error", "message": "Failed to update YAML frontmatter"}

class AnswerUpdate(BaseModel):
    subject: str
    year: str = None
    exam_id: str
    no: int
    new_answer: str

@app.post("/api/update_correct_answer")
def update_correct_answer(update: AnswerUpdate):
    # Reconstruct the Markdown filepath
    # Format: data_MD/{subject}/{year}/{exam_id}_{year}_{no}.md
    if update.year is None:
        raise HTTPException(status_code=400, detail="Year is required for markdown updates")
        
    md_path = data_md_path / update.subject / update.year / f"{update.exam_id}_{update.year}_{update.no}.md"
    
    if not md_path.exists():
        # Fallback: Maybe year is omitted in filename or something? Just raise for now.
        raise HTTPException(status_code=404, detail=f"Markdown file not found: {md_path}")
        
    success = update_user_data(md_path, {'current_answer': update.new_answer})
    if success:
        return {"status": "success"}
    return {"status": "error", "message": "Failed to update YAML frontmatter"}

# We keep this for frontend compatibility but it won't actually do anything useful in Markdown
class KeyConceptUpdate(BaseModel):
    subject: str
    year: str = None
    exam_id: str
    no: int
    new_key_concept: str

@app.post("/api/update_key_concept")
def update_key_concept(update: KeyConceptUpdate):
    return {"status": "success"}


app.mount("/", StaticFiles(directory=str(BASE_DIR / "public"), html=True), name="public")

import threading
import webbrowser

if __name__ == "__main__":
    import uvicorn
    # Open browser slightly after server starts
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8080/")).start()
    uvicorn.run(app, host="127.0.0.1", port=8080)
