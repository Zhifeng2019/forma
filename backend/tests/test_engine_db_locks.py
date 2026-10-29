import asyncio
import json

import httpx

from app import engine
from app.config import settings
from app.database import workspace_db
from app.jobs.context import JobContext, activate_job_context, reset_job_context
from app.jobs.leases import lease_next_job
from app.jobs.service import create_job
from app.security import encrypt_secret
from app.spec.defaults import local_default_appspec
from test_spec_review import make_project


class Response:
    def __init__(self, content):
        self.text = content
        self.status_code = 200
        self.headers = {}

    def json(self):
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': self.text}}]}


class Client:
    responses = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, _url, **_kwargs):
        return self.responses.pop(0)


def provider():
    return {
        'name': 'DeepSeek', 'model': 'deepseek-chat', 'base_url': 'https://api.example.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }


def spec(backend_mode='static'):
    return local_default_appspec('Contract Review', 'A reviewable workspace.', 'single-file', backend_mode)


def run_with_job(user_id, project_id, operation):
    with workspace_db(user_id) as db:
        job_id, _ = create_job(db, project_id, 'plan', 'lock-test', 'advance-stage', 'lock-trace')
        attempt = lease_next_job(db, 'lock-worker', job_id=job_id)
    context = JobContext(user_id, project_id, job_id, attempt['attempt_id'], 'lock-trace', asyncio.Event())
    token = activate_job_context(context)
    try:
        return asyncio.run(operation)
    finally:
        reset_job_context(token)


def test_plan_provider_telemetry_does_not_overlap_artifact_write_transaction(monkeypatch):
    user_id = 960600
    project_id = make_project(user_id)
    Client.responses = [Response(json.dumps({'document': '# Implementation plan'})),
                        Response(json.dumps(spec().model_dump(mode='json', exclude_none=True)))]
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_kwargs: Client())
    monkeypatch.setattr(settings, 'appspec_v1', True)
    run_with_job(user_id, project_id, engine._advance(user_id, project_id, provider()))
    with workspace_db(user_id) as db:
        project = db.execute('SELECT stage,status FROM projects WHERE id=?', (project_id,)).fetchone()
        assert project['stage'] == 'build' and project['status'] == 'ready'
        assert db.execute("SELECT COUNT(*) FROM artifacts WHERE project_id=? AND path='plan.md'", (project_id,)).fetchone()[0] == 1
        job_id = db.execute('SELECT id FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()['id']
        assert db.execute('SELECT COUNT(*) FROM tool_runs WHERE job_id=?', (job_id,)).fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM usage_ledger WHERE job_id=?', (job_id,)).fetchone()[0] == 2


def test_plan_revision_provider_telemetry_does_not_overlap_description_write(monkeypatch):
    user_id = 960601
    project_id = make_project(user_id, stage='build')
    with workspace_db(user_id) as db:
        db.execute("INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)",
                   (project_id, 'plan', 'plan.md', '# Original plan', 0))
    Client.responses = [Response(json.dumps({'document': '# Revised plan'})),
                        Response(json.dumps(spec().model_dump(mode='json', exclude_none=True)))]
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_kwargs: Client())
    monkeypatch.setattr(settings, 'appspec_v1', True)
    run_with_job(user_id, project_id, engine._revise_document(user_id, project_id, provider(), 'Clarify the first phase'))
    with workspace_db(user_id) as db:
        description = db.execute('SELECT description FROM projects WHERE id=?', (project_id,)).fetchone()['description']
        assert 'Clarify the first phase' in description
        content = db.execute("SELECT content FROM artifacts WHERE project_id=? AND path='plan.md'", (project_id,)).fetchone()['content']
        assert content == '# Revised plan'
        job_id = db.execute('SELECT id FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()['id']
        assert db.execute('SELECT COUNT(*) FROM tool_runs WHERE job_id=?', (job_id,)).fetchone()[0] == 2


def test_prebuild_migration_provider_telemetry_does_not_overlap_architecture_write(monkeypatch):
    user_id = 960602
    project_id = make_project(user_id)
    Client.responses = [Response(json.dumps(spec('fastapi').model_dump(mode='json', exclude_none=True)))]
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_kwargs: Client())
    monkeypatch.setattr(settings, 'appspec_v1', True)
    run_with_job(user_id, project_id, engine._migrate_architecture(user_id, project_id, 'fastapi', provider(), ''))
    with workspace_db(user_id) as db:
        backend_mode = db.execute('SELECT backend_mode FROM projects WHERE id=?', (project_id,)).fetchone()['backend_mode']
        assert backend_mode == 'fastapi'
        job_id = db.execute('SELECT id FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()['id']
        assert db.execute('SELECT COUNT(*) FROM tool_runs WHERE job_id=?', (job_id,)).fetchone()[0] == 1
