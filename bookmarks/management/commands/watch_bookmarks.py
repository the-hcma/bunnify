from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser

from bookmarks.models import Bookmark

# Get logger for this module
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Watch bunnify.json file for changes and reload automatically"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path.home() / "work" / "bunnify" / "bunnify.json"),
            help="Path to the JSON file to watch",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=2,
            help="Check interval in seconds (default: 2)",
        )

    def get_file_hash(self, filepath: Path) -> str | None:
        """Calculate SHA256 hash of file contents"""
        try:
            return hashlib.sha256(filepath.read_bytes()).hexdigest()
        except Exception:
            return None

    def handle(self, *args: Any, **options: Any) -> None:
        json_file_path = Path(options["file"]).resolve()
        interval = options["interval"]

        logger.info(
            f"Starting file watcher for: {json_file_path}, interval: {interval}s"
        )

        if not json_file_path.exists():
            logger.error(f"File not found: {json_file_path}")
            self.stdout.write(self.style.ERROR(f"File not found: {json_file_path}"))
            return

        self.stdout.write(
            self.style.SUCCESS(f"👀 Watching {json_file_path} for changes...")
        )
        self.stdout.write(f"Check interval: {interval} seconds\n")

        last_hash = self.get_file_hash(json_file_path)
        logger.debug(f"Initial file hash: {last_hash}")

        try:
            while True:
                time.sleep(interval)
                current_hash = self.get_file_hash(json_file_path)

                if current_hash and current_hash != last_hash:
                    logger.info(
                        f"File change detected in {json_file_path}, hash changed from {last_hash} to {current_hash}"
                    )
                    self.stdout.write(
                        self.style.WARNING(f"\n🔄 Change detected in {json_file_path}")
                    )
                    self.stdout.write("Reloading bookmarks...")

                    try:
                        # Reload bookmarks
                        logger.info("Reloading bookmarks via load_bookmarks command")
                        call_command(
                            "load_bookmarks", file=str(json_file_path), verbosity=0
                        )

                        # Count loaded bookmarks
                        count = Bookmark.objects.count()
                        logger.info(f"Successfully reloaded {count} bookmarks")
                        self.stdout.write(
                            self.style.SUCCESS(f"✓ Reloaded {count} bookmarks\n")
                        )
                    except Exception as e:
                        logger.error(f"Error reloading bookmarks: {e}", exc_info=True)
                        self.stdout.write(self.style.ERROR(f"✗ Error reloading: {e}\n"))

                    last_hash = current_hash

        except KeyboardInterrupt:
            logger.info("File watcher stopped by user (KeyboardInterrupt)")
            self.stdout.write(self.style.WARNING("\n\n👋 Stopped watching for changes"))
