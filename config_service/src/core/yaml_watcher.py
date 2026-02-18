"""
YAML Config File Watcher

Watches config/local.yaml for changes and automatically reloads configuration
into the database when running in local mode.
"""

import time
from pathlib import Path
from threading import Thread
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.core.audit_log import app_logger
from src.core.yaml_config import (
    YAMLConfigManager,
    is_local_mode,
    is_write_back_suppressed,
)
from src.core.yaml_seeder import seed_from_yaml
from src.core.yaml_validator import validate_yaml_config
from src.db.session import get_session_maker

logger = app_logger().bind(component="yaml_watcher")


class YAMLConfigHandler(FileSystemEventHandler):
    """Handler for YAML config file changes."""

    def __init__(self, config_file_path: str):
        self.config_file_path = Path(config_file_path).resolve()
        self.last_reload_time = 0
        self.debounce_seconds = 1  # Debounce multiple rapid changes

    def on_modified(self, event: FileSystemEvent):
        """Handle file modification events."""
        if event.is_directory:
            return

        # Check if the modified file is our config file
        modified_path = Path(event.src_path).resolve()
        if modified_path != self.config_file_path:
            return

        # Skip events caused by the system's own write-back (DB → YAML).
        # Seeding from those would undo the DB change that triggered the write.
        if is_write_back_suppressed():
            logger.debug("Skipping watcher event — triggered by system write-back")
            return

        # Debounce rapid changes (editors often write multiple times)
        current_time = time.time()
        if current_time - self.last_reload_time < self.debounce_seconds:
            return

        self.last_reload_time = current_time

        logger.info(
            f"Detected change in {self.config_file_path.name}, reloading config..."
        )

        try:
            # Validate before applying — hard block on errors
            yaml_manager = YAMLConfigManager(str(self.config_file_path))
            resolved = yaml_manager.load_config()
            result = validate_yaml_config(resolved)

            if result.warnings:
                for w in result.warnings:
                    logger.warning(f"⚠️  YAML warning: {w}")

            if not result.is_valid:
                logger.error(
                    "❌ local.yaml has validation errors — not applying changes. "
                    "Fix the file and save again.\n" + result.format()
                )
                return

            # Reload config from YAML and update database
            SessionLocal = get_session_maker()
            db = SessionLocal()
            try:
                seeded = seed_from_yaml(db, str(self.config_file_path), force=True)
                if seeded:
                    logger.info("✅ Configuration reloaded successfully")
                else:
                    logger.warning("⚠️  Configuration reload skipped (no changes)")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to reload config: {e}", exc_info=True)


class YAMLConfigWatcher:
    """Watches YAML config file for changes and triggers reloads."""

    def __init__(self, config_file_path: str = "config/local.yaml"):
        self.config_file_path = Path(config_file_path)
        self.observer: Optional[Observer] = None
        self.handler: Optional[YAMLConfigHandler] = None

    def start(self):
        """Start watching the config file for changes."""
        if not is_local_mode():
            logger.debug("Not in local mode, file watcher disabled")
            return

        if not self.config_file_path.exists():
            logger.warning(
                f"Config file not found: {self.config_file_path}, file watcher disabled"
            )
            return

        # Watch the directory containing the config file
        watch_dir = self.config_file_path.parent

        self.handler = YAMLConfigHandler(str(self.config_file_path))
        self.observer = Observer()
        self.observer.schedule(self.handler, str(watch_dir), recursive=False)
        self.observer.start()

        logger.info(
            f"🔍 Watching {self.config_file_path} for changes (auto-reload enabled)"
        )

    def stop(self):
        """Stop watching the config file."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            logger.info("File watcher stopped")


def start_yaml_watcher_background(config_file_path: str = "config/local.yaml"):
    """
    Start the YAML config file watcher in a background thread.

    This function is non-blocking and returns immediately.
    The watcher runs in the background and automatically reloads
    configuration when the file changes.

    Args:
        config_file_path: Path to the YAML config file to watch
    """
    watcher = YAMLConfigWatcher(config_file_path)

    def run_watcher():
        try:
            watcher.start()
            # Keep the watcher thread alive
            while True:
                time.sleep(1)
        except Exception as e:
            logger.error(f"File watcher thread error: {e}", exc_info=True)

    # Start watcher in daemon thread (will exit when main process exits)
    thread = Thread(target=run_watcher, daemon=True, name="yaml-watcher")
    thread.start()

    return watcher
