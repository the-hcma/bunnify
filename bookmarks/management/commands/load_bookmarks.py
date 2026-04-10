from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from jsonschema import ValidationError, validate

from bookmarks.models import Bookmark

# Get logger for this module
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Load bookmarks from bunnify.json file"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path.home() / "work" / "bunnify" / "bunnify.json"),
            help="Path to the JSON file containing bookmarks",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        json_file_path = Path(options["file"]).resolve()
        logger.info(f"Loading bookmarks from: {json_file_path}")

        # Define JSON schema for validation
        schema = {
            "type": "object",
            "patternProperties": {
                "^[a-zA-Z0-9_]+$": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "url": {"type": "string"},
                        "old-url": {"type": "string"},
                        "oldurl": {"type": "string"},
                    },
                    "required": ["description", "url"],
                }
            },
        }

        self.stdout.write(f"📖 Loading bookmarks from: {json_file_path}")

        try:
            # Read and parse JSON file
            data = json.loads(json_file_path.read_text(encoding="utf-8"))

            # Validate schema
            logger.info("Starting JSON schema validation")
            validate(instance=data, schema=schema)
            logger.info("JSON schema validation passed")
            self.stdout.write(self.style.SUCCESS(f"✓ JSON schema validation passed"))

            # Check for reserved keywords
            reserved_keywords = ["h", "help"]
            for key in data.keys():
                if key in reserved_keywords:
                    logger.error(
                        f"Reserved keyword violation: bookmark key '{key}' is reserved"
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f'Error: Bookmark key "{key}" is reserved and cannot be used.\n'
                            f'Reserved keywords: {", ".join(reserved_keywords)}'
                        )
                    )
                    return

            # Clear existing bookmarks
            existing_count = Bookmark.objects.count()
            Bookmark.objects.all().delete()
            logger.info(f"Cleared {existing_count} existing bookmarks")
            self.stdout.write(self.style.WARNING("Cleared existing bookmarks"))

            # Load bookmarks
            created_count = 0
            for key, bookmark_data in data.items():
                # Handle both "old-url" and "oldurl" variants
                old_url = bookmark_data.get("old-url") or bookmark_data.get("oldurl")
                defaults = bookmark_data.get("defaults", {})

                Bookmark.objects.create(
                    key=key,
                    description=bookmark_data["description"],
                    url=bookmark_data["url"],
                    old_url=old_url,
                    defaults=defaults,
                )
                created_count += 1
                logger.debug(
                    f"Created bookmark: key='{key}', url='{bookmark_data['url']}'"
                )

            logger.info(f"Successfully loaded {created_count} bookmarks")
            self.stdout.write(
                self.style.SUCCESS(f"✓ Successfully loaded {created_count} bookmarks")
            )

        except FileNotFoundError:
            logger.error(f"File not found: {json_file_path}")
            self.stdout.write(
                self.style.ERROR(f"Error: File not found: {json_file_path}")
            )
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format: {e}", exc_info=True)
            self.stdout.write(self.style.ERROR(f"Error: Invalid JSON format: {e}"))
        except ValidationError as e:
            logger.error(f"Schema validation failed: {e.message}", exc_info=True)
            self.stdout.write(
                self.style.ERROR(f"Error: Schema validation failed: {e.message}")
            )
        except Exception as e:
            logger.error(f"Unexpected error loading bookmarks: {e}", exc_info=True)
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
