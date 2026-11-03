import json
import uuid

from app.database import workspace_db, workspace_for
from app.spec.review import appspec_review
from app.spec.schema import appspec_document
from fixtures.archived_appspec import archived_package


def make_project(user_id: int, stage: str = 'plan') -> str:
    workspace_for(user_id)
    project_id = uuid.uuid4().hex
    with workspace_db(user_id) as db:
        db.execute('''INSERT INTO projects(id,name,brief,stage,backend_mode,source_format)
            VALUES(?,?,?,?,?,?)''', (
            project_id, 'Contract Review', 'A reviewable workspace with persistent items.',
            stage, 'static', 'single-file',
        ))
    return project_id



def test_historical_contract_remains_readable():
    package = archived_package()
    review = appspec_review(appspec_document(package.spec))
    assert review['appspec_valid'] is True
    assert review['appspec']['spec_hash'] == package.spec_hash


def test_historical_review_detects_hash_mismatch():
    package = archived_package()
    envelope = json.loads(appspec_document(package.spec))
    envelope['spec']['product']['name'] = 'Changed without rehashing'
    review = appspec_review(json.dumps(envelope))
    assert review['appspec_valid'] is False
    assert 'hash does not match' in review['appspec_error']
