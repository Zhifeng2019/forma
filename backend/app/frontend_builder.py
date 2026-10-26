"""Materialize, build, and package multi-file frontend applications."""

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import zipfile

from .config import settings
from .source_packages import frontend_package_json, frontend_vite_config


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


def write_source_files(project_id: str, version: int, files: dict[str, str]) -> Path:
    root = version_directory(project_id, version)
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = safe_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_text() != content:
            raise PackageBuildError(f'Immutable version source differs at {relative}')
        target.write_text(content)
    return root


def _digest(files: dict[str, str]) -> str:
    payload = json.dumps(files, sort_keys=True) + frontend_package_json() + frontend_vite_config() + 'vite-react-package-v1'
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
    process = await asyncio.create_subprocess_exec(
        *command, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        await _terminate(process)
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise PackageBuildError(f'{action} timed out. Please retry.') from exc
    text = output.decode(errors='replace')
    if process.returncode:
        raise PackageBuildError(f'{action} failed:\n{text[-3000:]}')
    return text


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


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
    root = write_source_files(project_id, version, files)
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
        node_root = await ensure_node_environment(user_id)
        node, npm = _node_binaries()
        shared_modules = node_root / 'node_modules'
        local_modules = frontend / 'node_modules'
        if local_modules.is_symlink():
            local_modules.unlink()
        elif local_modules.exists():
            shutil.rmtree(local_modules)
        local_modules.symlink_to(shared_modules, target_is_directory=True)
        env = _environment(root, shared_modules, node)
        await _run([npm, 'run', 'build'], frontend, env, settings.runtime_build_timeout, 'Frontend production build')
        if not index.exists():
            raise PackageBuildError('Vite completed without producing frontend/dist/index.html.')
        marker.write_text(digest)
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
            if relative.parts[0] == 'backend' and backend_mode != 'fastapi':
                continue
            if path.name.startswith('.forma-') or path.suffix in {'.pyc', '.sqlite', '.db'}:
                continue
            archive.write(path, str(relative))
    return buffer.getvalue()
