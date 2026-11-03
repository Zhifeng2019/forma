"""Isolate every test suite before any application module is imported."""

import os
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

TEST_ROOT = Path(__file__).parents[2] / 'data' / 'test-runtimes'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
TEST_DATA = Path(tempfile.mkdtemp(prefix='forma-test-', dir=TEST_ROOT))
os.environ['DATA_DIR'] = str(TEST_DATA)
os.environ['SECRET_KEY'] = 'test-secret-key-with-at-least-32-bytes'
os.environ['RUNTIME_PYTHON'] = sys.executable
os.environ['STUDIO_BASE_URL'] = 'http://testserver'
os.environ['APPS_BASE_URL'] = 'http://apps.localhost'
os.environ['CORS_ORIGINS'] = 'http://localhost:5173,http://127.0.0.1:5173'
# Each suite starts from the supported source-generation defaults; opt-in
# runtime and job tests enable their independent flags explicitly.
os.environ['DURABLE_JOBS_V1'] = 'false'
os.environ['ACCEPTANCE_GATE_V1'] = 'false'
os.environ['SANDBOX_V1'] = 'false'


@pytest.fixture(autouse=True)
def forget_provider_capabilities():
    # Learned provider capabilities are process-wide; each test starts from none.
    from app import llm
    llm._SCHEMA_UNSUPPORTED.clear()
    yield
    llm._SCHEMA_UNSUPPORTED.clear()


def pytest_sessionfinish(session, exitstatus):
    del session, exitstatus
    shutil.rmtree(TEST_DATA, ignore_errors=True)
