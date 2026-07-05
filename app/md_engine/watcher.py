import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from .cache_builder import update_single_file_cache

class MarkdownChangeHandler(FileSystemEventHandler):
    def __init__(self, data_md_dir: Path, output_dir: Path):
        super().__init__()
        self.data_md_dir = data_md_dir
        self.output_dir = output_dir
        
        # Debounce mechanism
        self.last_modified = {}
        self.debounce_seconds = 2.0

    def handle_event(self, event):
        if event.is_directory or not event.src_path.endswith('.md'):
            return
            
        filepath = Path(event.src_path)
        
        try:
            # For deletion events, filepath.stat() will fail, so we handle it.
            if not filepath.exists():
                # Allow deletion to pass through
                if filepath in self.last_modified:
                    del self.last_modified[filepath]
            else:
                current_mtime = filepath.stat().st_mtime
                if filepath in self.last_modified:
                    if current_mtime <= self.last_modified[filepath]:
                        return # File wasn't actually modified (e.g. read access or attribute change)
                self.last_modified[filepath] = current_mtime
        except Exception:
            pass
            
        print(f"[Watcher] Detected change in {filepath.name}")
        update_single_file_cache(filepath, self.data_md_dir, self.output_dir)

    def on_modified(self, event):
        self.handle_event(event)

    def on_created(self, event):
        self.handle_event(event)
        
    def on_deleted(self, event):
        self.handle_event(event)

def start_watcher(data_md_dir: Path, output_dir: Path) -> Observer:
    """
    啟動 Watchdog 監控資料夾。
    """
    event_handler = MarkdownChangeHandler(data_md_dir, output_dir)
    observer = Observer()
    observer.schedule(event_handler, str(data_md_dir), recursive=True)
    observer.start()
    print(f"[Watcher] Started watching {data_md_dir} for changes...")
    return observer
