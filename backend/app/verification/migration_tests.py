"""Generate migration-history and republishing acceptance checks."""

from .common import AcceptanceContext, GeneratedCheck, HTTP_HELPERS


def generate_migration_tests(context: AcceptanceContext) -> tuple[dict[str, str], list[GeneratedCheck]]:
    current_mode = context.spec.architecture.backend_mode
    target_mode = 'static' if current_mode == 'fastapi' else 'fastapi'
    source = f'''"""Generated migration and republication checks."""
import os
import unittest

{HTTP_HELPERS}
CURRENT_MODE = {current_mode!r}
TARGET_MODE = {target_mode!r}


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.project_id = os.environ.get('PROJECT_ID', '')
        if not self.project_id:
            raise RuntimeError('PROJECT_ID is required')
        if not os.environ.get('FORMA_TOKEN'):
            raise RuntimeError('FORMA_TOKEN is required')
        status, self.original = request('GET', f'/api/projects/{{self.project_id}}', studio=True)
        if status != 200:
            raise RuntimeError(f'Unable to load project for migration checks: {{status}}')

    def test_migration_preserves_phase_and_publication(self):
        before_phase = self.original['phase_index']
        before_version = self.original['current_version']
        before_published = self.original['published_version']
        try:
            status, migrated = request('POST', f'/api/projects/{{self.project_id}}/architecture',
                                       {{'target_mode': TARGET_MODE, 'defer': False}}, studio=True)
            self.assertEqual(status, 200, migrated)
            self.assertEqual(migrated['phase_index'], before_phase)
            self.assertEqual(migrated['published_version'], before_published)
            self.assertEqual(migrated['backend_mode'], TARGET_MODE)
            historical = next(row for row in migrated['versions'] if row['version'] == before_version)
            self.assertEqual(historical['backend_mode'], CURRENT_MODE)
            if self.original.get('published_url'):
                status, _body = request('GET', '', raw_url=self.original['published_url'])
                self.assertEqual(status, 200)
        finally:
            request('POST', f'/api/projects/{{self.project_id}}/architecture',
                    {{'target_mode': CURRENT_MODE, 'defer': False}}, studio=True)

    def test_republish_preserves_history(self):
        version = self.original['current_version']
        previous_publication = self.original['published_version']
        try:
            status, published = request('POST', f'/api/projects/{{self.project_id}}/publish',
                                        {{'version': version}}, studio=True)
            self.assertEqual(status, 200, published)
            self.assertEqual(published['published_version'], version)
            current = next(row for row in published['versions'] if row['version'] == version)
            self.assertEqual(current['backend_mode'], CURRENT_MODE)
            status, _body = request('GET', '', raw_url=published['published_url'])
            self.assertEqual(status, 200)
        finally:
            if previous_publication is None:
                request('POST', f'/api/projects/{{self.project_id}}/unpublish', studio=True)
            else:
                request('POST', f'/api/projects/{{self.project_id}}/publish',
                        {{'version': previous_publication}}, studio=True)


if __name__ == '__main__':
    unittest.main()
'''
    environment = ('FORMA_BASE_URL', 'FORMA_TOKEN', 'PROJECT_ID')
    checks = [
        GeneratedCheck('migration.preserves-phase-and-publication', 'migration', target_mode,
                       'test_migration_preserves_phase_and_publication', 'acceptance/migration_tests.py',
                       required=False, mutates=True, environment=environment),
        GeneratedCheck('migration.republish-preserves-history', 'migration', 'republish',
                       'test_republish_preserves_history', 'acceptance/migration_tests.py',
                       required=False, mutates=True, environment=environment),
    ]
    return {'acceptance/migration_tests.py': source}, checks
