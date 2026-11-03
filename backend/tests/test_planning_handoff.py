import asyncio
import hashlib
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import engine
from app.backend_engine import local_backend_html, local_backend_source
from app.config import settings
from app.database import workspace_db, workspace_for
from app.generation_context import DOCUMENT_PATHS, read_version_context
from app.jobs.snapshots import capture_attempt_snapshot, discard_attempt_snapshot, rollback_attempt_snapshot
from app.llm import GenerationError
from app.main import app
from app.source_packages import local_source_package


DOCUMENTS = {
    'product.md': '# Product\nRequire an invoice approval trail. Product-only decision: AUDIT-742.',
    'design.md': '# Design\nUse an accessible timeline. Design-only decision: TIMELINE-829.',
    'plan.md': '# Plan\n## Phase 1\nRead invoices: READ-133.\n## Phase 2\nApprove invoices: APPROVE-287.\n## Phase 3\nExport audit history: EXPORT-691.',
}
PROVIDER = {'name': 'Handoff test', 'model': 'fixture-model'}


def make_project(source_format='single-file', backend_mode='static', stage='build'):
    user_id = 975100
    workspace_for(user_id)
    project_id = uuid.uuid4().hex
    with workspace_db(user_id) as db:
        db.execute('''INSERT INTO projects(id,name,brief,description,stage,stage_index,backend_mode,source_format)
            VALUES(?,?,?,?,?,?,?,?)''',
            (project_id, 'Invoice Trail', 'A focused invoice tool.', 'Keep amounts in EUR.', stage,
             {'design': 1, 'plan': 2, 'build': 3}[stage], backend_mode, source_format))
        for path, content in DOCUMENTS.items():
            engine.save_artifact(db, project_id, {'product.md': 'discovery', 'design.md': 'design', 'plan.md': 'plan'}[path],
                                 path, content, 0)
    return user_id, project_id


def source_response(source_format, mode):
    if source_format == 'multi-file':
        return {'files': local_source_package('Invoice Trail', 'Test workflow', 1, mode)}
    if mode == 'fastapi':
        return {'html': local_backend_html('Invoice Trail', 'Test workflow', 1),
                'python': local_backend_source('Invoice Trail')}
    return {'html': '<!doctype html><html><body>Invoice trail</body></html>'}


def saved_context(user_id, project_id, version):
    with workspace_db(user_id) as db:
        return read_version_context(db.execute('SELECT generation_context FROM versions WHERE project_id=? AND version=?',
                                              (project_id, version)).fetchone()[0])


def test_documents_flow_into_design_plan_and_document_revisions(monkeypatch):
    user_id, project_id = make_project(stage='design')
    prompts = []
    responses = [
        {'document': DOCUMENTS['design.md']}, {'document': DOCUMENTS['plan.md']},
        {'document': DOCUMENTS['plan.md'] + '\nPhase 1 correction: ROUND-623.'},
    ]

    async def complete(_provider, _system, prompt):
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(engine, 'complete', complete)
    asyncio.run(engine._advance(user_id, project_id, PROVIDER, 'Use keyboard navigation.'))
    asyncio.run(engine._advance(user_id, project_id, PROVIDER, 'Keep the first phase small.'))
    asyncio.run(engine._revise_document(user_id, project_id, PROVIDER, 'Correct rounding in phase 1.'))
    assert DOCUMENTS['product.md'] in prompts[0]
    assert DOCUMENTS['design.md'] not in prompts[0] and DOCUMENTS['plan.md'] not in prompts[0]
    assert 'Use keyboard navigation.' in prompts[0]
    assert DOCUMENTS['product.md'] in prompts[1] and DOCUMENTS['design.md'] in prompts[1]
    assert DOCUMENTS['plan.md'] not in prompts[1]
    assert 'Keep the first phase small.' in prompts[1]
    assert all(content in prompts[2] for content in DOCUMENTS.values())
    with workspace_db(user_id) as db:
        project = engine.get_project(db, project_id)
        assert (project['stage'], project['phase_index'], project['current_version']) == ('build', 0, 0)
        assert db.execute('SELECT COUNT(*) FROM versions WHERE project_id=?', (project_id,)).fetchone()[0] == 0


@pytest.mark.parametrize('source_format', ['single-file', 'multi-file'])
@pytest.mark.parametrize('backend_mode', ['static', 'fastapi'])
def test_builds_refinements_and_migrations_keep_the_reviewed_inputs(monkeypatch, source_format, backend_mode):
    user_id, project_id = make_project(source_format, backend_mode)
    prompts = []
    target_mode = backend_mode

    async def complete(_provider, _system, prompt):
        prompts.append(prompt)
        return source_response(source_format, target_mode)

    async def built(*_args, **_kwargs):
        return '<html></html>'

    monkeypatch.setattr(engine, 'complete', complete)
    monkeypatch.setattr(engine, 'ensure_frontend_build', built)
    asyncio.run(engine._advance(user_id, project_id, PROVIDER))
    first = saved_context(user_id, project_id, 1)
    assert first['phase'] == 1 and first['operation'] == 'build'
    assert first['document_basis'] == 'workflow' and first['generation_mode'] == 'llm'
    assert first['missing_documents'] == []
    for path, content in DOCUMENTS.items():
        assert first['documents'][path]['content'] == content
        assert first['documents'][path]['sha256'] == hashlib.sha256(content.encode()).hexdigest()
    with workspace_db(user_id) as db:
        db.execute('UPDATE projects SET published_version=1 WHERE id=?', (project_id,))
        # Simulate a later draft/import. It must not replace the reviewed inputs of an existing app.
        engine.save_artifact(db, project_id, 'plan', 'plan.md', '# Unapproved replacement: DRAFT-999.', 0)
    asyncio.run(engine._advance(user_id, project_id, PROVIDER, 'Improve the invoice labels.', revise=True))
    asyncio.run(engine._advance(user_id, project_id, PROVIDER))
    target_mode = 'static' if backend_mode == 'fastapi' else 'fastapi'
    asyncio.run(engine._migrate_architecture(user_id, project_id, target_mode, PROVIDER, 'Preserve the approval trail.'))
    assert len(prompts) == 4
    for prompt in prompts:
        assert all(content in prompt for content in DOCUMENTS.values())
        assert prompt.index(DOCUMENTS['product.md']) < prompt.index(DOCUMENTS['design.md']) < prompt.index(DOCUMENTS['plan.md'])
        assert 'DRAFT-999' not in prompt
        assert 'Keep amounts in EUR.' in prompt
    assert 'phase 1/3' in prompts[0] and 'phase 1/3' in prompts[1] and 'phase 2/3' in prompts[2]
    assert 'do not advance the plan' in prompts[3]
    assert 'Improve the invoice labels.' in prompts[1] and 'Preserve the approval trail.' in prompts[3]
    for version, operation, phase in [(2, 'refine', 1), (3, 'build', 2), (4, 'migrate', 2)]:
        context = saved_context(user_id, project_id, version)
        assert (context['operation'], context['phase']) == (operation, phase)
        assert context['documents'] == first['documents']
        assert context['inherited_from_version'] == version - 1
    assert saved_context(user_id, project_id, 1) == first
    with workspace_db(user_id) as db:
        project = engine.get_project(db, project_id)
        assert (project['phase_index'], project['current_version'], project['published_version']) == (2, 4, 1)
        for version in range(1, 5):
            assert not set(DOCUMENT_PATHS) & engine.generation_source_files(db, project_id, version).keys()
            assert not db.execute('''SELECT 1 FROM artifacts WHERE project_id=? AND version=?
                AND path IN ('product.md','design.md','plan.md')''', (project_id, version)).fetchone()


def test_package_repair_keeps_snapshot_and_cannot_overwrite_reviewed_plan(monkeypatch):
    user_id, project_id = make_project('multi-file')
    prompts = []

    async def complete(_provider, _system, prompt):
        prompts.append(prompt)
        response = source_response('multi-file', 'static')
        if len(prompts) == 1:
            response['files']['plan.md'] = '# Model rewrote the reviewed plan.'
            with workspace_db(user_id) as db:
                engine.save_artifact(db, project_id, 'plan', 'plan.md', '# Concurrent draft: NEW-552.', 0)
        return response

    async def built(*_args, **_kwargs):
        return '<html></html>'

    monkeypatch.setattr(engine, 'complete', complete)
    monkeypatch.setattr(engine, 'ensure_frontend_build', built)
    asyncio.run(engine._advance(user_id, project_id, PROVIDER))
    assert len(prompts) == 2
    assert all(DOCUMENTS['plan.md'] in prompt and 'NEW-552' not in prompt for prompt in prompts)
    assert 'reviewed planning document' in prompts[1]
    assert saved_context(user_id, project_id, 1)['documents']['plan.md']['content'] == DOCUMENTS['plan.md']
    with workspace_db(user_id) as db:
        assert db.execute("SELECT content FROM artifacts WHERE project_id=? AND path='plan.md'",
                          (project_id,)).fetchone()[0] == '# Concurrent draft: NEW-552.'


@pytest.mark.parametrize('durable', [False, True])
@pytest.mark.parametrize('defer', [False, True])
def test_plan_feedback_requires_explicit_first_build_approval(monkeypatch, durable, defer):
    monkeypatch.setattr(settings, 'durable_jobs_v1', durable)
    with TestClient(app) as client:
        account = client.post('/api/auth/register', json={
            'email': f'plan-{uuid.uuid4().hex}@example.com', 'name': 'Plan Reviewer', 'password': 'password123',
        }).json()
        headers = {'Authorization': f'Bearer {account["token"]}'}
        project = client.post('/api/projects', headers=headers, json={
            'name': 'Manual plan', 'brief': 'A personal invoice list.', 'backend_mode': 'static',
            'source_format': 'single-file', 'auto_mode': False,
        }).json()
        project_id = project['id']
        for _ in range(2):
            project = client.post(f'/api/projects/{project_id}/advance', headers=headers, json={}).json()
        assert project['stage'] == 'build' and project['current_version'] == 0
        feedback = 'Phase 1 must display invoice currency without conversion.'
        response = client.post(f'/api/projects/{project_id}/messages', headers=headers, json={'content': feedback, 'defer': defer})
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 10
        while response.json()['status'] == 'working' and time.monotonic() < deadline:
            time.sleep(0.02)
            response = client.get(f'/api/projects/{project_id}', headers=headers)
        project = response.json()
        assert (project['status'], project['stage'], project['current_version'], project['phase_index']) == ('ready', 'build', 0, 0)
        assert project['versions'] == []
        plan = next(artifact['content'] for artifact in project['artifacts'] if artifact['path'] == 'plan.md')
        assert feedback in plan
        assert not any('index.html' in artifact['path'] for artifact in project['artifacts'])
        project = client.post(f'/api/projects/{project_id}/advance', headers=headers, json={}).json()
        assert project['current_version'] == 1 and project['phase_index'] == 1
        provenance = client.get(f'/api/projects/{project_id}/versions/1/context', headers=headers).json()
        assert provenance['recorded'] and provenance['context']['documents']['plan.md']['content'] == plan
        other = client.post('/api/auth/register', json={
            'email': f'other-{uuid.uuid4().hex}@example.com', 'name': 'Other Reviewer', 'password': 'password123',
        }).json()
        assert client.get(f'/api/projects/{project_id}/versions/1/context').status_code == 401
        assert client.get(f'/api/projects/{project_id}/versions/1/context', headers={
            'Authorization': f'Bearer {other["token"]}',
        }).status_code == 404


def test_direct_refinement_cannot_bypass_plan_approval():
    user_id, project_id = make_project()
    asyncio.run(engine._advance(user_id, project_id, None, 'Keep the first phase small.', revise=True))
    with workspace_db(user_id) as db:
        assert engine.get_project(db, project_id)['current_version'] == 0
        assert 'Keep the first phase small.' in db.execute(
            "SELECT content FROM artifacts WHERE project_id=? AND path='plan.md'", (project_id,),
        ).fetchone()[0]


def test_legacy_versions_are_not_given_fabricated_input_history(monkeypatch):
    user_id, project_id = make_project()
    with workspace_db(user_id) as db:
        db.execute('DELETE FROM artifacts WHERE project_id=?', (project_id,))
        db.execute("UPDATE projects SET current_version=1,phase_index=1,published_version=1 WHERE id=?", (project_id,))
        db.execute("INSERT INTO versions(project_id,version,label) VALUES(?,1,'Historical')", (project_id,))
        engine.save_artifact(db, project_id, 'build', 'index.html', '<html>Existing application</html>', 1)

    async def complete(_provider, _system, prompt):
        assert 'Documents unavailable: product.md, design.md, plan.md' in prompt
        assert '<html>Existing application</html>' in prompt
        return source_response('single-file', 'static')

    monkeypatch.setattr(engine, 'complete', complete)
    asyncio.run(engine._advance(user_id, project_id, PROVIDER, 'Keep the application working.', revise=True))
    assert saved_context(user_id, project_id, 1) is None
    current = saved_context(user_id, project_id, 2)
    assert current['document_basis'] == 'legacy-unrecorded'
    assert current['documents'] == {} and current['missing_documents'] == list(DOCUMENT_PATHS)


def test_input_history_survives_cancellation_rollback():
    user_id, project_id = make_project()
    asyncio.run(engine._advance(user_id, project_id, None))
    before = saved_context(user_id, project_id, 1)
    snapshot = capture_attempt_snapshot(user_id, project_id, 'context-rollback', 1, 'verify-package', {'version': 1})
    try:
        with workspace_db(user_id) as db:
            db.execute("UPDATE versions SET generation_context=NULL WHERE project_id=?", (project_id,))
        rollback_attempt_snapshot(snapshot)
        assert saved_context(user_id, project_id, 1) == before
    finally:
        discard_attempt_snapshot(snapshot)


def test_changed_planning_inputs_change_durable_job_identity(monkeypatch):
    monkeypatch.setattr(settings, 'durable_jobs_v1', True)
    user_id, project_id = make_project()
    recorded = []

    async def record(_user, _project, _stage, _action, inputs, _operation):
        recorded.append(inputs)

    monkeypatch.setattr(engine, 'run_generation_job', record)
    asyncio.run(engine.generate_stage(user_id, project_id, PROVIDER))
    with workspace_db(user_id) as db:
        engine.save_artifact(db, project_id, 'plan', 'plan.md', DOCUMENTS['plan.md'] + '\nCorrected phase 1.', 0)
    asyncio.run(engine.generate_stage(user_id, project_id, PROVIDER))
    assert recorded[0]['planning_inputs'] != recorded[1]['planning_inputs']


def test_corrupt_recorded_context_fails_without_replacing_history(monkeypatch):
    user_id, project_id = make_project()
    asyncio.run(engine._advance(user_id, project_id, None))
    context = saved_context(user_id, project_id, 1)
    context['documents']['plan.md']['content'] = 'Content changed without updating its revision hash.'
    with workspace_db(user_id) as db:
        db.execute('UPDATE versions SET generation_context=? WHERE project_id=?', (json.dumps(context), project_id))

    async def forbidden(*_args, **_kwargs):
        raise AssertionError('A corrupt context must fail before calling the provider')

    monkeypatch.setattr(engine, 'complete', forbidden)
    with pytest.raises(GenerationError, match='saved generation context is invalid'):
        asyncio.run(engine._advance(user_id, project_id, PROVIDER))
    with workspace_db(user_id) as db:
        assert engine.get_project(db, project_id)['current_version'] == 1
    monkeypatch.setattr(settings, 'durable_jobs_v1', True)
    asyncio.run(engine.generate_stage(user_id, project_id, PROVIDER))
    with workspace_db(user_id) as db:
        assert engine.get_project(db, project_id)['status'] == 'error'
        assert db.execute('SELECT status FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()[0] == 'failed'


@pytest.mark.parametrize('durable', [False, True])
def test_failed_build_does_not_record_a_version_or_change_its_predecessor(monkeypatch, durable):
    user_id, project_id = make_project()
    asyncio.run(engine._advance(user_id, project_id, None))
    before = saved_context(user_id, project_id, 1)
    monkeypatch.setattr(settings, 'durable_jobs_v1', durable)

    async def fail(*_args, **_kwargs):
        raise GenerationError('Deliberate generation failure')

    monkeypatch.setattr(engine, 'complete', fail)
    asyncio.run(engine.generate_stage(user_id, project_id, PROVIDER))
    with workspace_db(user_id) as db:
        project = engine.get_project(db, project_id)
        assert project['current_version'] == 1 and project['status'] == 'error'
        assert db.execute('SELECT COUNT(*) FROM versions WHERE project_id=?', (project_id,)).fetchone()[0] == 1
    assert saved_context(user_id, project_id, 1) == before
