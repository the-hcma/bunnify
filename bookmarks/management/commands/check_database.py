from __future__ import annotations

import logging
import sys
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check if the database is properly initialized and ready'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed diagnostic information'
        )

    def handle(self, *args: Any, **options: Any) -> None:
        verbose = options.get('verbose', False)
        
        all_checks_passed = True
        
        # Check 1: Database file/connection
        try:
            connection.ensure_connection()
            self.stdout.write('✓ Database connection OK')
            if verbose:
                self.stdout.write(f'  Engine: {connection.settings_dict.get("ENGINE", "unknown")}')
                self.stdout.write(f'  Name: {connection.settings_dict.get("NAME", "unknown")}')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Database connection failed: {e}'))
            all_checks_passed = False
            return

        # Check 2: Migrations status
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        
        # Get pending migrations
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        
        if plan:
            self.stdout.write(
                self.style.WARNING(f'⚠ Database has {len(plan)} pending migration(s)')
            )
            if verbose:
                for migration, backward in plan:
                    self.stdout.write(f'  - {migration.app}.{migration.name}')
            all_checks_passed = False
        else:
            self.stdout.write('✓ All migrations applied')

        # Check 3: Required tables exist (Bookmark model)
        from bookmarks.models import Bookmark
        
        try:
            # Try a simple query to verify table exists
            count = Bookmark.objects.count()
            self.stdout.write(f'✓ Database tables OK ({count} bookmarks in database)')
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Database tables missing or corrupted: {e}')
            )
            all_checks_passed = False

        # Final status
        self.stdout.write('')
        if all_checks_passed:
            self.stdout.write(self.style.SUCCESS('✅ Database is ready!'))
            return
        else:
            self.stdout.write(self.style.WARNING('⚠ Database needs initialization'))
            self.stdout.write('')
            self.stdout.write('To initialize the database, run:')
            self.stdout.write('  uv run python manage.py migrate')
            self.stdout.write('')
            sys.exit(1)
