"""Load checked-in fixtures without reading or overwriting application data."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.database import CONTROL_SCHEMA, WORKSPACE_SCHEMA, connect

FIXTURE_ROOT = Path(__file__).resolve().parent
WORKSPACE_MARKER = '.forma-fixture-workspace'
_KEY_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]*$')


class FixtureError(RuntimeError):
    pass


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or '\\' in value or '\x00' in value or path.is_absolute()
            or value != path.as_posix() or any(part in {'.', '..'} for part in path.parts)):
        raise ValueError(f'Fixture paths must be canonical relative POSIX paths: {value!r}')
    return value


class FixtureModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Resource(FixtureModel):
    source: str
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    @field_validator('source')
    @classmethod
    def safe_source(cls, value: str) -> str:
        return _relative_path(value)


class ArtifactFixture(Resource):
    path: str
    stage: str = Field(default='build', min_length=1)

    @field_validator('path')
    @classmethod
    def safe_artifact_path(cls, value: str) -> str:
        return _relative_path(value)


class VersionFixture(FixtureModel):
    version: int = Field(ge=1)
    label: str = Field(min_length=1)
    note: str = ''
    backend_mode: Literal['static', 'fastapi']
    source_format: Literal['single-file', 'multi-file']
    artifacts: list[ArtifactFixture] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_artifacts(self):
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError('Fixture version contains duplicate artifact paths')
        return self


class ProjectFixture(FixtureModel):
    key: str
    project_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    name: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    description: str = ''
    stage: str = 'build'
    stage_index: int = Field(default=3, ge=0, le=5)
    phase_index: int = Field(default=1, ge=0, le=3)
    status: str = 'ready'
    auto_mode: bool = False
    backend_mode: Literal['static', 'fastapi']
    backend_reason: str = 'Checked-in compatibility fixture'
    source_format: Literal['single-file', 'multi-file']
    published_version: int | None = Field(default=None, ge=1)
    current_version: int = Field(ge=0)
    versions: list[VersionFixture]

    @field_validator('key')
    @classmethod
    def safe_key(cls, value: str) -> str:
        if not _KEY_PATTERN.fullmatch(value):
            raise ValueError('Fixture keys must contain lowercase letters, numbers, and hyphens')
        return value

    @model_validator(mode='after')
    def valid_version_references(self):
        versions = {version.version: version for version in self.versions}
        if len(versions) != len(self.versions):
            raise ValueError('Fixture project contains duplicate versions')
        if self.current_version and self.current_version not in versions:
            raise ValueError('current_version must reference a materialized version')
        if self.published_version and self.published_version not in versions:
            raise ValueError('published_version must reference a materialized version')
        if self.published_version and self.published_version > self.current_version:
            raise ValueError('published_version cannot exceed current_version')
        if self.current_version:
            current = versions[self.current_version]
            if (current.backend_mode, current.source_format) != (self.backend_mode, self.source_format):
                raise ValueError('Current project architecture must match current_version')
        return self


class ProviderFixture(Resource):
    status_code: int = Field(default=200, ge=100, le=599)
    content_type: str = 'application/json'


class FixtureManifest(FixtureModel):
    schema_version: Literal['1.0']
    fixture_pack_version: str = Field(pattern=r'^[a-z0-9][a-z0-9.-]*$')
    appspecs: dict[str, Resource]
    providers: dict[str, ProviderFixture]
    projects: list[ProjectFixture]

    @model_validator(mode='after')
    def unique_projects_and_keys(self):
        for key in [*self.appspecs, *self.providers]:
            if not _KEY_PATTERN.fullmatch(key):
                raise ValueError(f'Invalid fixture key: {key!r}')
        keys = [project.key for project in self.projects]
        project_ids = [project.project_id for project in self.projects]
        if len(keys) != len(set(keys)) or len(project_ids) != len(set(project_ids)):
            raise ValueError('Fixture projects must have unique keys and project IDs')
        return self


@dataclass(frozen=True)
class MaterializedProject:
    key: str
    project_id: str
    user_id: int
    data_dir: Path
    control_db: Path
    workspace_db: Path
    project_dir: Path
    current_version: int
    published_version: int | None


@dataclass(frozen=True)
class MaterializedProvider:
    key: str
    path: Path
    status_code: int
    content_type: str
    body: str


class FixturePack:
    def __init__(self, root: Path = FIXTURE_ROOT):
        self.root = root.resolve()
        try:
            document = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
            self.manifest = FixtureManifest.model_validate(document)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise FixtureError(f'Unable to load fixture manifest: {exc}') from exc
        self.fixture_pack_version = self.manifest.fixture_pack_version
        self.projects = {project.key: project for project in self.manifest.projects}

    def read_resource(self, resource: Resource) -> str:
        source = self.root.joinpath(*PurePosixPath(resource.source).parts).resolve()
        if not source.is_relative_to(self.root) or not source.is_file():
            raise FixtureError(f'Fixture resource is unavailable: {resource.source}')
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != resource.sha256:
            raise FixtureError(f'Fixture resource checksum mismatch: {resource.source}')
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise FixtureError(f'Fixture resource must be UTF-8 text: {resource.source}') from exc

    def appspec(self, key: str) -> dict:
        try:
            resource = self.manifest.appspecs[key]
        except KeyError as exc:
            raise FixtureError(f'Unknown AppSpec fixture: {key}') from exc
        try:
            return json.loads(self.read_resource(resource))
        except json.JSONDecodeError as exc:
            raise FixtureError(f'AppSpec fixture is not valid JSON: {key}') from exc

    def workspace(self, data_dir: Path) -> 'FixtureWorkspace':
        return FixtureWorkspace(self, data_dir)


class FixtureWorkspace:
    def __init__(self, pack: FixturePack, data_dir: Path):
        if not data_dir.is_absolute():
            raise FixtureError('Fixture workspaces require an explicit absolute temporary path')
        self.pack = pack
        self.data_dir = data_dir.resolve()
        self.control_db = self.data_dir / 'control.db'
        self.marker = self.data_dir / WORKSPACE_MARKER
        if self.data_dir.exists() and not self.data_dir.is_dir():
            raise FixtureError('Fixture workspace path is not a directory')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.marker.exists():
            if self.marker.read_text(encoding='utf-8') != pack.fixture_pack_version:
                raise FixtureError('Fixture workspace belongs to a different fixture-pack version')
        else:
            if any(self.data_dir.iterdir()):
                raise FixtureError('Refusing to use a nonempty directory that is not a fixture workspace')
            self.marker.write_text(pack.fixture_pack_version)

    @contextmanager
    def database(self, path: Path):
        db = connect(path)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def workspace_db(self, user_id: int) -> Path:
        return self.data_dir / 'users' / f'user_{user_id}.db'

    def ensure_user(self, user_id: int) -> None:
        if type(user_id) is not int or user_id <= 0:
            raise FixtureError('Fixture user IDs must be positive integers')
        email = f'fixture-{user_id}@example.invalid'
        self.control_db.parent.mkdir(parents=True, exist_ok=True)
        with self.database(self.control_db) as control:
            control.executescript(CONTROL_SCHEMA)
            control.execute('INSERT OR IGNORE INTO users(id,email,name,password_hash) VALUES(?,?,?,?)',
                            (user_id, email, 'Fixture User', 'not-a-password'))
            existing = control.execute('SELECT email FROM users WHERE id=?', (user_id,)).fetchone()
            if existing['email'] != email:
                raise FixtureError(f'Fixture user ID {user_id} is already in use')
            control.execute('INSERT OR IGNORE INTO preferences(user_id) VALUES(?)', (user_id,))
        workspace_path = self.workspace_db(user_id)
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.database(workspace_path) as workspace:
            workspace.executescript(WORKSPACE_SCHEMA)

    def materialize_project(self, key: str, user_id: int = 910001) -> MaterializedProject:
        try:
            project = self.pack.projects[key]
        except KeyError as exc:
            raise FixtureError(f'Unknown project fixture: {key}') from exc
        # Validate every resource before creating databases or writing source files.
        prepared = [
            (version, artifact, self.pack.read_resource(artifact))
            for version in project.versions for artifact in version.artifacts
        ]
        self.ensure_user(user_id)
        workspace_path = self.workspace_db(user_id)
        project_dir = self.data_dir / 'projects' / project.project_id
        with self.database(workspace_path) as workspace:
            if workspace.execute('SELECT 1 FROM projects WHERE id=?', (project.project_id,)).fetchone():
                raise FixtureError(f'Project fixture is already materialized: {key}')
            workspace.execute('''INSERT INTO projects(
                id,name,brief,description,stage,stage_index,phase_index,status,auto_mode,
                backend_mode,backend_reason,source_format,published_version,current_version)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                project.project_id, project.name, project.brief, project.description, project.stage,
                project.stage_index, project.phase_index, project.status, int(project.auto_mode),
                project.backend_mode, project.backend_reason, project.source_format,
                project.published_version, project.current_version,
            ))
            for version in project.versions:
                workspace.execute('''INSERT INTO versions(
                    project_id,version,label,note,backend_mode,source_format) VALUES(?,?,?,?,?,?)''', (
                    project.project_id, version.version, version.label, version.note,
                    version.backend_mode, version.source_format,
                ))
            for version, artifact, content in prepared:
                workspace.execute('''INSERT INTO artifacts(project_id,stage,path,content,version)
                    VALUES(?,?,?,?,?)''', (
                    project.project_id, artifact.stage, artifact.path, content, version.version,
                ))
                target = project_dir / 'versions' / f'v{version.version}'
                target = target.joinpath(*PurePosixPath(artifact.path).parts).resolve()
                if not target.is_relative_to(project_dir.resolve()):
                    raise FixtureError(f'Artifact path escapes its version: {artifact.path}')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
        if project.published_version:
            published = next(version for version in project.versions
                             if version.version == project.published_version)
            with self.database(self.control_db) as control:
                control.execute('''INSERT INTO deployment_registry(
                    project_id,user_id,published_version,backend_mode,source_format,runtime_metadata)
                    VALUES(?,?,?,?,?,?)''', (
                    project.project_id, user_id, project.published_version,
                    published.backend_mode, published.source_format, '{}',
                ))
        return MaterializedProject(
            key=key, project_id=project.project_id, user_id=user_id, data_dir=self.data_dir,
            control_db=self.control_db, workspace_db=workspace_path, project_dir=project_dir,
            current_version=project.current_version, published_version=project.published_version,
        )

    def materialize_provider(self, key: str) -> MaterializedProvider:
        try:
            provider = self.pack.manifest.providers[key]
        except KeyError as exc:
            raise FixtureError(f'Unknown provider fixture: {key}') from exc
        body = self.pack.read_resource(provider)
        target = self.data_dir / 'provider-responses' / f'{key}.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        return MaterializedProvider(
            key=key, path=target, status_code=provider.status_code,
            content_type=provider.content_type, body=body,
        )


def query_one(path: Path, sql: str, parameters: tuple = ()) -> sqlite3.Row:
    """Read one fixture row without using the application's configured database."""
    db = connect(path)
    try:
        row = db.execute(sql, parameters).fetchone()
        if row is None:
            raise FixtureError('Expected fixture database row was not found')
        return row
    finally:
        db.close()
