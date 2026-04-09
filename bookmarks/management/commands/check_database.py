from __future__ import annotations

import logging
import sys
from typing import Any

from django.core.management import call_command
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
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Automatically fix database issues by running migrations'
        )

    def handle(self, *args: Any, **options: Any) -> None:
        verbose = options.get('verbose', False)
        should_fix = options.get('fix', False)
        
        all_checks_passed = True
        issues_found = []
        
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
            issues_found.append('pending_migrations')
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
            issues_found.append('missing_tables')

        # Final status
        self.stdout.write('')
        if all_checks_passed:
            self.stdout.write(self.style.SUCCESS('✅ Database is ready!'))
            return
        
        # Database has issues
        if should_fix:
            self._fix_database(issues_found)
        else:
            self._show_fix_instructions()

    def _show_fix_instructions(self) -> None:
        """Show instructions on how to fix database issues."""
        self.stdout.write(self.style.WARNING('⚠ Database needs initialization'))
        self.stdout.write('')
        self.stdout.write('To initialize the database, run:')
        self.stdout.write('  uv run python manage.py migrate')
        self.stdout.write('')
        sys.exit(1)

    def _fix_database(self, issues_found: list[str]) -> None:
        """Automatically fix database issues by running migrations."""
        if 'pending_migrations' in issues_found or 'missing_tables' in issues_found:
            self.stdout.write(self.style.WARNING('🔧 Attempting to fix database issues...'))
            self.stdout.write('')
            
            try:
                # Run migrations to fix the database
                self.stdout.write('📦 Running database migrations...')
                call_command('migrate', interactive=False, verbosity=0)
                self.stdout.write(self.style.SUCCESS('✓ Migrations completed'))
                self.stdout.write('')
                
                # Re-check the database to confirm it's fixed
                self.stdout.write('🔄 Verifying database after migration...')
                self.stdout.write('')
                
                # Refresh database connection to see changes
                connection.close()
                connection.ensure_connection()
                
                # Re-run all checks
                all_checks_passed = self._run_checks()
                
                if all_checks_passed:
                    self.stdout.write(self.style.SUCCESS('✅ Database successfully initialized!'))
                    return
                else:
                    self.stdout.write(
                        self.style.ERROR('✗ Database issues persist after migration')
                    )
                    self.stdout.write('')
                    sys.exit(1)
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'✗ Error during migration: {e}')
                )
                self.stdout.write('')
                self.stdout.write('To fix this manually, run:')
                self.stdout.write('  uv run python manage.py migrate')
                self.stdout.write('')
                sys.exit(1)

    def _run_checks(self) -> bool:
        """Run all checks and return True if all passed, False otherwise."""
        all_passed = True
        
        # Check 1: Database connection
        try:
            connection.ensure_connection()
            self.stdout.write('✓ Database connection OK')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Database connection failed: {e}'))
            return False

        # Check 2: Migrations
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        
        if plan:
            self.stdout.write(
                self.style.WARNING(f'⚠ Database has {len(plan)} pending migration(s)')
            )
            all_passed = False
        else:
            self.stdout.write('✓ All migrations applied')

        # Check 3: Tables
        from bookmarks.models import Bookmark
        
        try:
            count = Bookmark.objects.count()
            self.stdout.write(f'✓ Database tables OK ({count} bookmarks in database)')
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Database tables missing or corrupted: {e}')
            )
            all_passed = False
        
        return all_passed

