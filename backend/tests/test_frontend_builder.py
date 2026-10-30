import asyncio
import uuid

import pytest

from app.config import settings
from app.frontend_builder import (
    PackageBuildError, ensure_frontend_build, staging_directory, version_directory,
)
from app.source_packages import local_source_package


def fake_node_environment(monkeypatch):
    root = settings.data_path / 'fake-node' / uuid.uuid4().hex
    (root / 'node_modules').mkdir(parents=True)
    monkeypatch.setattr('app.frontend_builder._node_binaries', lambda: ('node', 'npm'))

    async def environment(_user_id):
        return root

    monkeypatch.setattr('app.frontend_builder.ensure_node_environment', environment)
    return root


def successful_build(calls):
    async def run(command, cwd, _env, _timeout, _action, **_kwargs):
        calls.append((command, cwd))
        dist = cwd / 'dist'
        assets = dist / 'assets'
        assets.mkdir(parents=True)
        (dist / 'index.html').write_text('<html><script src="./assets/app.js"></script></html>')
        (assets / 'app.js').write_text('console.log("built")')
        return ''

    return run


def test_build_uses_staging_then_promotes_and_reuses_cache(monkeypatch):
    monkeypatch.setattr('app.frontend_builder._node_binaries', lambda: ('node', 'npm'))
    fake_node_environment(monkeypatch)
    calls = []
    monkeypatch.setattr('app.frontend_builder._run', successful_build(calls))
    project_id = uuid.uuid4().hex
    files = local_source_package('Staging Check', 'Deterministic staging', 1, 'static')
    html = asyncio.run(ensure_frontend_build(940100, project_id, 1, files))
    root = version_directory(project_id, 1)
    staging = staging_directory(project_id, 1)
    assert calls[0][0] == ['npm', 'run', 'build']
    assert calls[0][1] == staging / 'frontend'
    assert (root / 'frontend' / 'dist' / 'index.html').read_text() == html
    assert not staging.exists() and not root.with_name('v1.rejected').exists()
    for path in files:
        assert (root / path).is_file()
    assert asyncio.run(ensure_frontend_build(940100, project_id, 1, files)) == html
    assert len(calls) == 1


def test_failed_build_preserves_last_usable_version(monkeypatch):
    fake_node_environment(monkeypatch)
    project_id = uuid.uuid4().hex
    root = version_directory(project_id, 1)
    dist = root / 'frontend' / 'dist'
    dist.mkdir(parents=True)
    (dist / 'index.html').write_text('last usable version')
    files = local_source_package('Failure Check', 'Preserve previous version', 1, 'static')

    async def fail(*_args, **_kwargs):
        raise PackageBuildError('Deliberate build failure')

    monkeypatch.setattr('app.frontend_builder._run', fail)
    with pytest.raises(PackageBuildError, match='Deliberate build failure'):
        asyncio.run(ensure_frontend_build(940101, project_id, 1, files))
    assert (dist / 'index.html').read_text() == 'last usable version'
    assert not (root / 'frontend' / 'src' / 'App.tsx').exists()
    assert not staging_directory(project_id, 1).exists()


def test_incomplete_attempt_is_promoted_only_after_success(monkeypatch):
    fake_node_environment(monkeypatch)
    calls = []
    monkeypatch.setattr('app.frontend_builder._run', successful_build(calls))
    project_id = uuid.uuid4().hex
    files = local_source_package('Recovery Check', 'Complete failed directory', 1, 'static')
    root = version_directory(project_id, 1)
    workspace = root / 'frontend' / 'src' / 'components' / 'Workspace.tsx'
    workspace.parent.mkdir(parents=True)
    workspace.write_text(files['frontend/src/components/Workspace.tsx'])
    asyncio.run(ensure_frontend_build(940102, project_id, 1, files))
    assert (root / 'frontend' / 'src' / 'App.tsx').is_file()
    assert (root / 'frontend' / 'src' / 'components' / 'Workspace.tsx').read_text() == files['frontend/src/components/Workspace.tsx']
    assert (root / 'frontend' / 'dist' / 'index.html').is_file()
    assert not staging_directory(project_id, 1).exists()


def test_changed_source_is_rejected_without_starting_a_build(monkeypatch):
    fake_node_environment(monkeypatch)
    project_id = uuid.uuid4().hex
    files = local_source_package('Immutable Check', 'Do not overwrite changed source', 1, 'static')
    root = version_directory(project_id, 1)
    app = root / 'frontend' / 'src' / 'App.tsx'
    app.parent.mkdir(parents=True)
    app.write_text('locally changed source')
    calls = []
    monkeypatch.setattr('app.frontend_builder._run', successful_build(calls))
    with pytest.raises(PackageBuildError, match='Immutable version source differs'):
        asyncio.run(ensure_frontend_build(940103, project_id, 1, files))
    assert calls == []
    assert app.read_text() == 'locally changed source'
    assert not staging_directory(project_id, 1).exists()
