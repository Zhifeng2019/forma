import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.backend_engine import default_requirements
from app.config import settings
from app.runtime import runtime_manager
from app.runtime_sandbox import DockerSandbox


def test_sandbox_arguments_enforce_nonroot_readonly_workspace_and_resource_limits():
    sandbox = DockerSandbox()
    source = Path('/tmp/forma-source')
    work = Path('/tmp/forma-work')
    args = sandbox.run_arguments('forma-image', 'forma-test', source, work, 51234)
    user = args[args.index('--user') + 1]
    assert user != '0:0'
    assert '--read-only' in args
    assert args[args.index('--cap-drop') + 1] == 'ALL'
    assert 'no-new-privileges' in args
    assert args[args.index('--pids-limit') + 1] == '128'
    assert args[args.index('--memory') + 1] == f'{settings.runtime_memory_mb}m'
    assert args[args.index('--cpus') + 1] == '1'
    assert 'noexec' in args[args.index('--tmpfs') + 1]
    source_mount = next(argument for argument in args if argument.startswith('type=bind,src=') and 'dst=/app/source' in argument)
    work_mount = next(argument for argument in args if argument.startswith('type=bind,src=') and 'dst=/app/work' in argument)
    assert source_mount.endswith('forma-source,dst=/app/source,readonly')
    assert work_mount.endswith('forma-work,dst=/app/work') and 'readonly' not in work_mount
    assert all('/.venv' not in argument for argument in args)
    assert args[args.index('--publish') + 1] == '127.0.0.1:51234:51234'


def test_sandbox_image_installs_dependencies_inside_container_not_host_venv():
    dockerfile = DockerSandbox()._dockerfile()
    assert dockerfile.startswith('FROM python:3.13-slim')
    assert 'RUN python -m venv /app/venv' in dockerfile
    assert '/app/venv/bin/pip install' in dockerfile
    assert 'COPY requirements.txt /app/requirements.txt' in dockerfile


@pytest.mark.skipif(os.environ.get('FORMA_DOCKER_SMOKE') != 'true', reason='Opt-in real Docker smoke test')
def test_real_docker_sandbox_health_and_filesystem_limits(monkeypatch):
    project_id = 'a' * 32
    key = f'{project_id}:v1:preview'
    source_dir = settings.data_path / 'test-runtimes' / 'sandbox-smoke-source'
    work = settings.data_path / 'test-runtimes' / 'sandbox-smoke-work'
    for path in (source_dir, work, settings.data_path / 'projects' / project_id):
        shutil.rmtree(path, ignore_errors=True)
    source_dir.mkdir(parents=True)
    (source_dir / 'main.py').write_text(
        'from fastapi import FastAPI\n'
        'app = FastAPI()\n'
        '@app.get("/api/health")\n'
        'def health():\n'
        '    return {"status": "ok"}\n',
    )
    (source_dir / 'requirements.txt').write_text(default_requirements())
    monkeypatch.setattr(settings, 'sandbox_v1', True)

    async def scenario():
        runtime = await runtime_manager._start(
            key, project_id, 1, 'preview', Path(sys.executable), source_dir,
        )
        try:
            status = await runtime_manager.status(project_id, 1, check_health=True)
            assert status['healthy'] is True and status['execution'] == 'docker-container'
            container = json.loads(subprocess.check_output(['docker', 'inspect', runtime.process.name], text=True))[0]
            assert container['Config']['User'] not in {'', '0', '0:0'}
            assert container['HostConfig']['ReadonlyRootfs'] is True
            assert container['HostConfig']['PidsLimit'] == 128
            assert container['HostConfig']['Memory'] == settings.runtime_memory_mb * 1024 * 1024
            assert container['HostConfig']['NanoCpus'] == 1_000_000_000
            subprocess.run(['docker', 'exec', runtime.process.name, 'sh', '-c', 'touch /app/work/verified'], check=True)
            assert subprocess.run(
                ['docker', 'exec', runtime.process.name, 'sh', '-c', 'touch /app/source/forbidden'],
                capture_output=True, check=False,
            ).returncode != 0
            assert subprocess.run(
                ['docker', 'exec', runtime.process.name, 'sh', '-c', 'touch /etc/forbidden'],
                capture_output=True, check=False,
            ).returncode != 0
        finally:
            await runtime_manager.stop_project(project_id)
        remaining = subprocess.check_output(
            ['docker', 'ps', '--all', '--quiet', '--filter', f'name={runtime.process.name}'], text=True,
        )
        assert not remaining.strip()

    try:
        asyncio.run(scenario())
    finally:
        for path in (source_dir, work, settings.data_path / 'projects' / project_id):
            shutil.rmtree(path, ignore_errors=True)
