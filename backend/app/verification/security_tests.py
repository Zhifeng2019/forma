"""Generate deterministic source, dependency, and archive security checks."""

from ..source_packages import FRONTEND_DEPENDENCIES
from .common import AcceptanceContext, GeneratedCheck


def generate_security_tests(context: AcceptanceContext) -> tuple[dict[str, str], list[GeneratedCheck]]:
    spec = context.spec
    allowed_python = sorted({'fastapi', 'uvicorn', 'pydantic', 'email-validator', *spec.dependencies.python})
    source = f'''"""Generated deterministic security checks for an AppSpec package."""
import json
import os
from pathlib import Path
import re
import unittest
import zipfile

SOURCE = Path(os.environ.get('APP_SOURCE_DIR', '')).resolve()
ALLOWED_PYTHON = {allowed_python!r}
ALLOWED_NPM = {sorted(FRONTEND_DEPENDENCIES)!r}
SKIP = {{'node_modules', 'dist', '.venv', 'tmp', '__pycache__', 'acceptance'}}


def text_sources():
    if not SOURCE.is_dir():
        raise RuntimeError('APP_SOURCE_DIR must identify the generated version directory')
    for path in SOURCE.rglob('*'):
        if path.is_file() and not SKIP & set(path.parts) and path.suffix in {{'.py', '.js', '.jsx', '.html', '.json', '.css', '.txt'}}:
            yield path


class SecurityTests(unittest.TestCase):
    def test_no_embedded_credentials(self):
        patterns = [r'sk-[A-Za-z0-9]{{16,}}', r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
                    r'(?:OPENAI|DEEPSEEK|MOONSHOT|ANTHROPIC)_API_KEY']
        for path in text_sources():
            content = path.read_text(errors='replace')
            for pattern in patterns:
                self.assertIsNone(re.search(pattern, content), f'Potential credential in {{path}}')

    def test_no_host_environment_access(self):
        blocked = ['os.environ', 'os.getenv', 'process.env', 'import os', 'import subprocess',
                   'import socket', 'import pathlib', 'import shutil', 'import ctypes', 'import importlib']
        for path in text_sources():
            if path.suffix not in {{'.py', '.js', '.jsx'}}:
                continue
            content = path.read_text(errors='replace')
            for pattern in blocked:
                self.assertNotIn(pattern, content, f'Host access pattern in {{path}}')

    def test_reviewed_python_dependencies(self):
        for path in SOURCE.rglob('requirements.txt'):
            if SKIP & set(path.parts):
                continue
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                self.assertIn('==', line, f'Unpinned dependency in {{path}}: {{line}}')
                name = line.split('==', 1)[0].lower().replace('_', '-')
                self.assertIn(name, ALLOWED_PYTHON, f'Unreviewed dependency in {{path}}: {{name}}')

    def test_reviewed_npm_dependencies(self):
        if {spec.architecture.source_format == 'multi-file'!r}:
            package = json.loads((SOURCE / 'frontend' / 'package.json').read_text())
            dependencies = package.get('dependencies', {{}})
            self.assertEqual(set(dependencies), set(ALLOWED_NPM))
            for name, version in dependencies.items():
                self.assertTrue(version and isinstance(version, str), f'Unpinned npm dependency: {{name}}')

    def test_no_external_frontend_urls(self):
        pattern = re.compile(r'(?:fetch|Forma\\.api)\\s*\\(\\s*[\\'\"]https?://')
        for path in text_sources():
            if path.suffix in {{'.js', '.jsx', '.html'}}:
                self.assertIsNone(pattern.search(path.read_text(errors='replace')), f'External frontend URL in {{path}}')

    def test_archive_excludes_dependencies_and_caches(self):
        if {spec.architecture.source_format == 'multi-file'!r}:
            archive = os.environ.get('APP_PACKAGE_ZIP', '')
            if not archive:
                raise RuntimeError('APP_PACKAGE_ZIP is required for archive exclusion checks')
            with zipfile.ZipFile(archive) as package:
                for name in package.namelist():
                    self.assertFalse(any(part in name for part in ('node_modules', '.venv', '__pycache__', 'npm-cache', '/tmp/')), name)


if __name__ == '__main__':
    unittest.main()
'''
    checks = [
        GeneratedCheck('security.no-embedded-credentials', 'security', 'generated source',
                       'test_no_embedded_credentials', 'acceptance/security_tests.py',
                       environment=('APP_SOURCE_DIR',)),
        GeneratedCheck('security.no-host-environment-access', 'security', 'host environment',
                       'test_no_host_environment_access', 'acceptance/security_tests.py',
                       environment=('APP_SOURCE_DIR',)),
        GeneratedCheck('security.reviewed-dependencies', 'security', 'Python and npm dependencies',
                       'test_reviewed_python_dependencies', 'acceptance/security_tests.py',
                       environment=('APP_SOURCE_DIR',)),
        GeneratedCheck('security.no-external-frontend-urls', 'security', 'frontend network calls',
                       'test_no_external_frontend_urls', 'acceptance/security_tests.py',
                       environment=('APP_SOURCE_DIR',)),
    ]
    if spec.architecture.source_format == 'multi-file':
        checks.append(GeneratedCheck('security.archive-exclusions', 'security', 'deployment archive',
                                     'test_archive_excludes_dependencies_and_caches',
                                     'acceptance/security_tests.py', environment=('APP_SOURCE_DIR', 'APP_PACKAGE_ZIP')))
    return {'acceptance/security_tests.py': source}, checks
