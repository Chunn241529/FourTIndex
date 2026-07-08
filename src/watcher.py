import os
import sys
import time
import threading
from typing import Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.config import Config
from src.indexing_service import IndexingService

class CodebaseEventHandler(FileSystemEventHandler):
    def __init__(self, debounce_delay: float = 1.0, callback = None):
        super().__init__()
        self.debounce_delay = debounce_delay
        self.callback = callback
        self.changed_paths: Set[str] = set()
        self.timer: threading.Timer = None
        self.lock = threading.Lock()

    def on_any_event(self, event):
        if event.is_directory:
            return

        # Filter out common temporary/ignored paths early
        path = event.src_path
        normalized_path = path.replace("\\", "/")
        
        # Ignored directories
        ignored_patterns = [
            "/.git/", "/node_modules/", "/.fourtindex/", "/.venv/", 
            "/venv/", "/__pycache__/", "/.agents/", "/.gemini/", "/dist/", "/build/"
        ]
        if any(pattern in normalized_path for pattern in ignored_patterns):
            return
            
        # Ignored temporary file extensions
        ignored_extensions = [".tmp", ".swp", ".deleteme", "~"]
        if any(normalized_path.endswith(ext) for ext in ignored_extensions):
            return

        with self.lock:
            self.changed_paths.add(path)
            if self.timer is not None:
                self.timer.cancel()
            
            self.timer = threading.Timer(self.debounce_delay, self._trigger_callback)
            self.timer.start()

    def _trigger_callback(self):
        with self.lock:
            paths = list(self.changed_paths)
            self.changed_paths.clear()
            self.timer = None
        
        if paths and self.callback:
            self.callback(paths)

class CodebaseWatcher:
    def __init__(self, project_path: str, config: Config):
        self.project_path = os.path.abspath(project_path)
        self.config = config
        self.project_name = config.project_name
        self.indexing_service = IndexingService(config)
        
        self.event_handler = CodebaseEventHandler(
            debounce_delay=1.0, 
            callback=self._on_files_changed
        )
        self.observer = Observer()

    def _on_files_changed(self, paths):
        print(f"\n[Watcher] Detected changes in {len(paths)} file(s). Triggering incremental index...", file=sys.stderr)
        try:
            result = self.indexing_service.index_project(
                project_path=self.project_path,
                project_name=self.project_name
            )
            print(f"[Watcher] Incremental sync complete: {result.summary()}", file=sys.stderr)
        except Exception as e:
            print(f"[Watcher] Error during incremental index: {e}", file=sys.stderr)

    def start(self):
        """Starts the watcher observer synchronously (blocking)."""
        self.observer.schedule(self.event_handler, self.project_path, recursive=True)
        self.observer.start()
        print(f"[Watcher] Watching directory '{self.project_path}' for changes. Press Ctrl+C to stop.", file=sys.stderr)

    def stop(self):
        """Stops the watcher observer."""
        self.observer.stop()
        self.observer.join()

def start_watcher(project_path: str, config: Config):
    """Entry point for CLI standalone watcher."""
    watcher = CodebaseWatcher(project_path, config)
    watcher.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Watcher] Stopping codebase watcher...", file=sys.stderr)
        watcher.stop()

def start_background_watcher(project_path: str, config: Config) -> Observer:
    """Spawns codebase watcher observer on a background daemon thread."""
    watcher = CodebaseWatcher(project_path, config)
    watcher.observer.schedule(watcher.event_handler, watcher.project_path, recursive=True)
    watcher.observer.daemon = True
    watcher.observer.start()
    print(f"[Watcher] Background watcher started for '{watcher.project_path}'.", file=sys.stderr)
    return watcher.observer
