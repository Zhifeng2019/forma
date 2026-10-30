import asyncio
import json
import uuid

from app.api import project_payload
from app.config import Settings
from app.database import workspace_db, workspace_for
from app.spec.capabilities import assess_capabilities
from app.spec.compiler import compile_package
from app.spec.defaults import local_default_appspec
from app.spec.service import spec_artifacts
from app.verification.manifest import acceptance_artifacts
from app.verification.runner import verify_package

BROAD_BRIEF = (
    'Users register and login with a password. Admin configures SMTP so verification emails can be delivered. '
    'Users post images, comment, reply, follow, like or dislike, and share posts. '
    'Posts expire after one day and updates arrive over websocket.'
)


def broad_spec():
    spec = local_default_appspec('Social Product', BROAD_BRIEF, 'multi-file', 'static')
    document = spec.model_dump(mode='json', exclude_none=True)
    document['product']['primary_workflow'] = BROAD_BRIEF
    return document


def project_from_package(user_id, package):
    workspace_for(user_id)
    project_id = uuid.uuid4().hex
    with workspace_db(user_id) as db:
        db.execute('''INSERT INTO projects(id,name,brief,backend_mode,source_format,current_version)
            VALUES(?,?,?,?,?,1)''', (
            project_id, package.spec.product.name, package.spec.product.brief,
            package.spec.architecture.backend_mode, package.spec.architecture.source_format,
        ))
        db.execute('INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)',
                   (project_id, 1, 'Phase 2', package.spec.architecture.backend_mode,
                    package.spec.architecture.source_format))
        for path, content in {**package.files, **spec_artifacts(package)}.items():
            db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'build', path, content, 1))
    return project_id


def test_crud_scope_is_not_presented_as_full_product_coverage():
    spec = local_default_appspec('Task App', 'Create and complete focused tasks.', 'multi-file', 'static')
    assessment = assess_capabilities(spec)
    assert assessment['status'] == 'crud_scope'
    assert assessment['requirements'] == []
    assert 'not every possible product expectation' in assessment['summary']


def test_broad_brief_produces_deterministic_limitations_and_manifest_check():
    package = compile_package(broad_spec(), phase=2)
    artifacts = acceptance_artifacts(package)
    assessment = json.loads(artifacts['acceptance/capabilities.json'])
    assert assessment['status'] == 'limited'
    assert {item['id'] for item in assessment['requirements']} == {
        'authentication', 'authorization', 'related-workflows', 'binary-content',
        'external-integrations', 'scheduled-lifecycle', 'realtime',
    }
    manifest = json.loads(artifacts['acceptance/manifest.json'])
    check = next(item for item in manifest['checks'] if item['id'] == 'capability.declared-scope')
    assert check['required'] is True and check['file'] == 'studio:capability-review'
    assert manifest['capability']['summary'] == assessment['summary']


def test_supported_crud_passes_capability_gate():
    user_id = 990100
    package = compile_package(local_default_appspec(
        'Simple Tasks', 'Create and complete focused tasks.', 'multi-file', 'static',
    ), phase=2)
    project_id = project_from_package(user_id, package)
    report = asyncio.run(verify_package(
        user_id, project_id, 1,
        selected_check_ids={'build.production', 'capability.declared-scope'},
        config=Settings(acceptance_gate_v1=True),
    ))
    result = next(item for item in report['checks'] if item['id'] == 'capability.declared-scope')
    assert result['status'] == 'passed'
    assert report['capability']['status'] == 'crud_scope'


def test_limited_scaffold_is_blocked_and_visible_before_verification():
    user_id = 990101
    package = compile_package(broad_spec(), phase=2)
    project_id = project_from_package(user_id, package)
    early = project_payload(user_id, project_id)
    assert early['capability']['status'] == 'limited'
    assert early['capability']['requirements']

    report = asyncio.run(verify_package(
        user_id, project_id, 1,
        selected_check_ids={'build.production', 'capability.declared-scope'},
        config=Settings(acceptance_gate_v1=True),
    ))
    result = next(item for item in report['checks'] if item['id'] == 'capability.declared-scope')
    assert result['status'] == 'blocked'
    assert 'limited scaffold' in result['error']
    assert 'Narrow the product scope or extend the generator' in result['error']
    assert report['can_publish'] is False
    assert 'capability.declared-scope' in report['summary']['required_failures']
    assert report['capability']['status'] == 'limited'
