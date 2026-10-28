"""Materialize, build, and package multi-file frontend applications."""

import asyncio
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile

from .config import settings
from .jobs.processes import run_process
from .source_packages import frontend_package_json, frontend_vite_config
from .spec.schema import SPEC_ARTIFACT_PATHS


class PackageBuildError(RuntimeError):
    pass


def safe_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or '..' in pure.parts or str(pure) in {'', '.'}:
        raise PackageBuildError(f'Invalid package path: {relative}')
    root = root.resolve()
    target = (root / pure).resolve()
    if root != target and root not in target.parents:
        raise PackageBuildError(f'Package path escapes its version directory: {relative}')
    return target


def version_directory(project_id: str, version: int) -> Path:
    return settings.data_path / 'projects' / project_id / 'versions' / f'v{version}'


def staging_directory(project_id: str, version: int) -> Path:
    return version_directory(project_id, version).with_name(f'v{version}.staging')


def _remove_tree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _assert_immutable_source(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = safe_path(root, relative)
        if target.exists() and target.read_text() != content:
            raise PackageBuildError(f'Immutable version source differs at {relative}')


def _write_source_tree(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _assert_immutable_source(root, files)
    for relative, content in files.items():
        target = safe_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return root


def write_source_files(project_id: str, version: int, files: dict[str, str]) -> Path:
    return _write_source_tree(version_directory(project_id, version), files)


def _promote_version(staging: Path, root: Path) -> None:
    rejected = root.with_name(f'{root.name}.rejected')
    _remove_tree(rejected)
    if root.exists():
        root.rename(rejected)
    try:
        staging.rename(root)
    except Exception:
        if rejected.exists() and not root.exists():
            rejected.rename(root)
        raise
    _remove_tree(rejected)


def _digest(files: dict[str, str]) -> str:
    source = {path: content for path, content in files.items()
              if path not in SPEC_ARTIFACT_PATHS and not path.startswith('acceptance/')}
    payload = json.dumps(source, sort_keys=True) + frontend_package_json() + frontend_vite_config() + 'vite-react-package-v1'
    return hashlib.sha256(payload.encode()).hexdigest()


def _node_binaries() -> tuple[str, str]:
    node, npm = shutil.which('node'), shutil.which('npm')
    if not node or not npm:
        raise PackageBuildError('Node.js and npm are required to build multi-file frontend packages.')
    return node, npm


def _environment(root: Path, node_modules: Path, node_binary: str) -> dict[str, str]:
    (root / 'tmp').mkdir(parents=True, exist_ok=True)
    cache = settings.data_path / 'cache' / 'npm'
    cache.mkdir(parents=True, exist_ok=True)
    return {
        'PATH': f'{node_modules / ".bin"}:{Path(node_binary).parent}:/usr/local/bin:/usr/bin:/bin',
        'HOME': str(root), 'TMPDIR': str(root / 'tmp'),
        'NODE_ENV': 'production', 'NPM_CONFIG_REGISTRY': settings.runtime_npm_registry,
        'NPM_CONFIG_CACHE': str(cache), 'NPM_CONFIG_UPDATE_NOTIFIER': 'false',
        'NO_COLOR': '1',
    }


async def _run(command: list[str], cwd: Path, env: dict[str, str], timeout: int, action: str) -> str:
    try:
        result = await run_process(command, cwd, env, timeout, action)
    except TimeoutError as exc:
        raise PackageBuildError(f'{action} timed out. Please retry.') from exc
    if result.returncode:
        raise PackageBuildError(f'{action} failed:\n{result.output[-3000:]}')
    return result.output


_node_locks: dict[int, asyncio.Lock] = {}
_build_locks: dict[str, asyncio.Lock] = {}


async def ensure_node_environment(user_id: int) -> Path:
    root = settings.data_path / 'node' / f'user_{user_id}'
    node, npm = _node_binaries()
    async with _node_locks.setdefault(user_id, asyncio.Lock()):
        package_json = frontend_package_json()
        digest = hashlib.sha256(package_json.encode()).hexdigest()
        vite = root / 'node_modules' / '.bin' / 'vite'
        marker = root / '.forma-dependencies.sha256'
        if vite.exists() and marker.exists() and marker.read_text() == digest:
            return root
        root.mkdir(parents=True, exist_ok=True)
        (root / 'package.json').write_text(package_json)
        env = _environment(root, root / 'node_modules', node)
        await _run(
            [npm, 'install', '--ignore-scripts', '--no-audit', '--no-fund'],
            root, env, settings.runtime_build_timeout, 'Reviewed npm dependency installation',
        )
        if not vite.exists():
            raise PackageBuildError('The shared Node environment does not contain Vite after installation.')
        for package in ('react', 'react-dom', 'lucide-react', '@vitejs/plugin-react'):
            if not (root / 'node_modules' / package / 'package.json').exists():
                raise PackageBuildError(f'The shared Node environment is missing {package}.')
        marker.write_text(digest)
        return root


async def ensure_frontend_build(
    user_id: int, project_id: str, version: int, files: dict[str, str],
) -> str:
    root = version_directory(project_id, version)
    frontend = root / 'frontend'
    index = frontend / 'dist' / 'index.html'
    marker = frontend / 'dist' / '.forma-source.sha256'
    digest = _digest(files)
    if index.exists() and marker.exists() and marker.read_text() == digest:
        return index.read_text()
    key = f'{user_id}:{project_id}:v{version}'
    async with _build_locks.setdefault(key, asyncio.Lock()):
        if index.exists() and marker.exists() and marker.read_text() == digest:
            return index.read_text()
        _assert_immutable_source(root, files)
        staging = staging_directory(project_id, version)
        _remove_tree(staging)
        try:
            node_root = await ensure_node_environment(user_id)
            node, npm = _node_binaries()
            shared_modules = node_root / 'node_modules'
            _write_source_tree(staging, files)
            staged_frontend = staging / 'frontend'
            local_modules = staged_frontend / 'node_modules'
            local_modules.symlink_to(shared_modules, target_is_directory=True)
            env = _environment(staging, shared_modules, node)
            await _run([npm, 'run', 'build'], staged_frontend, env,
                       settings.runtime_build_timeout, 'Frontend production build')
            staged_index = staged_frontend / 'dist' / 'index.html'
            if not staged_index.exists():
                raise PackageBuildError('Vite completed without producing frontend/dist/index.html.')
            (staged_frontend / 'dist' / '.forma-source.sha256').write_text(digest)
            _promote_version(staging, root)
        except Exception:
            _remove_tree(staging)
            raise
        return index.read_text()


def frontend_asset_path(project_id: str, version: int, relative: str) -> Path:
    asset = safe_path(version_directory(project_id, version) / 'frontend' / 'dist' / 'assets', relative)
    if not asset.is_file():
        raise PackageBuildError('The requested frontend asset does not exist.')
    return asset


def deployment_archive(
    user_id: int, project_id: str, version: int, files: dict[str, str], backend_mode: str,
) -> bytes:
    root = write_source_files(project_id, version, files)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if not path.is_file() or {'node_modules', '__pycache__', 'npm-cache', 'tmp'} & set(path.parts):
                continue
            relative = path.relative_to(root)
            if relative.parts[0] == 'acceptance' and relative.name == 'deployment.zip':
                continue
            if relative.parts[0] == 'backend' and backend_mode != 'fastapi':
                continue
            if path.name.startswith('.forma-') or path.suffix in {'.pyc', '.sqlite', '.db'}:
                continue
            archive.write(path, str(relative))
    return buffer.getvalue()
