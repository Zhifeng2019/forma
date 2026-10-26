"""Isolate every test suite before any application module is imported."""

import os
from pathlib import Path
import shutil
import sys
import tempfile

TEST_ROOT = Path(__file__).parents[2] / 'data' / 'test-runtimes'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
TEST_DATA = Path(tempfile.mkdtemp(prefix='forma-test-', dir=TEST_ROOT))
os.environ['DATA_DIR'] = str(TEST_DATA)
os.environ['SECRET_KEY'] = 'test-secret-key-with-at-least-32-bytes'
os.environ['RUNTIME_PYTHON'] = sys.executable


def pytest_sessionfinish(session, exitstatus):
    del session, exitstatus
    shutil.rmtree(TEST_DATA, ignore_errors=True)
