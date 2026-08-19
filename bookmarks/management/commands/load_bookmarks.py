from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from jsonschema import ValidationError, validate

from app.completion_spec import parse_complete_map, validate_complete_map
from app.config import default_bookmarks_path
from bookmarks.models import Bookmark

# Get logger for this module
logger = logging.getLogger(__name__)


def _complete_map_errors(
    data: dict[str, Any],
) -> list[str]:
    """Validate every bookmark ``complete`` map before mutating the DB."""
    messages: list[str] = []
    for key, bookmark_data in data.items():
        complete_raw = bookmark_data.get("complete")
        complete = parse_complete_map(complete_raw)
        if complete_raw is not None and complete is None:
            messages.append(f'Invalid "complete" map for bookmark "{key}"')
            continue
        if complete:
            url = bookmark_data.get("url", "")
            if not isinstance(url, str):
                url = ""
            messages.extend(
                f'bookmark "{key}": {message}'
                for message in validate_complete_map(complete, url=url)
            )
    return messages


class Command(BaseCommand):
    help = "Load bookmarks from bunnify.json file"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--file",
            type=str,
            default=str(default_bookmarks_path()),
            help=(
                "Path to the JSON bookmarks file "
                "(default: ~/.config/bunnify/bookmarks.json; "
                "override with BUNNIFY_BOOKMARKS)"
            ),
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
                        "complete": {
                            "type": "object",
                            "patternProperties": {
                                "^[a-zA-Z_][a-zA-Z0-9_]*$": {
                                    "type": "object",
                                    "properties": {
                                        "kind": {
                                            "type": "string",
                                            "enum": [
                                                "github_issue",
                                                "github_org",
                                                "github_pull_request",
                                                "github_repo",
                                            ],
                                        },
                                        "org": {"type": "string"},
                                        "repo_param": {"type": "string"},
                                    },
                                    "required": ["kind"],
                                    "additionalProperties": False,
                                }
                            },
                            "additionalProperties": False,
                        },
                        "defaults": {"type": "object"},
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
            self.stdout.write(self.style.SUCCESS("✓ JSON schema validation passed"))

            # Check for reserved keywords
            reserved_keywords = ["h", "help"]
            for key in data.keys():
                if key in reserved_keywords:
                    logger.error(
                        f"Reserved keyword violation: bookmark key '{key}' is reserved"
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f'Error: Bookmark key "{key}" is reserved and '
                            f"cannot be used.\n"
                            f"Reserved keywords: {', '.join(reserved_keywords)}"
                        )
                    )
                    raise CommandError(
                        f'Bookmark key "{key}" is reserved and cannot be used.'
                    )

            complete_errors = _complete_map_errors(data)
            if complete_errors:
                for message in complete_errors:
                    logger.error("complete validation: %s", message)
                    self.stdout.write(self.style.ERROR(f"Error: {message}"))
                raise CommandError("Bookmark complete map validation failed")

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
                complete_raw = bookmark_data.get("complete")
                complete = parse_complete_map(complete_raw)

                Bookmark.objects.create(
                    key=key,
                    description=bookmark_data["description"],
                    url=bookmark_data["url"],
                    old_url=old_url,
                    defaults=defaults,
                    complete={
                        param: {
                            "kind": spec.kind,
                            **({"org": spec.org} if spec.org else {}),
                            **(
                                {"repo_param": spec.repo_param}
                                if spec.repo_param
                                else {}
                            ),
                        }
                        for param, spec in complete.items()
                    }
                    if complete
                    else {},
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
        except CommandError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error loading bookmarks: {e}", exc_info=True)
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
