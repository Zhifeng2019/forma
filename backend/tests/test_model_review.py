import asyncio
import json

import httpx

from app.api import verification_payload
from app.config import Settings
from app.database import workspace_db
from app.security import encrypt_secret
from app.verification.runner import verify_package
from test_verification_runner import dummy_check, verification_project


class Response:
    def __init__(self, content):
        self.status_code = 200
        self.text = content
        self.headers = {}

    def json(self):
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': self.text}}]}


class Client:
    response = None
    calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, _url, **_kwargs):
        type(self).calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def provider():
    return {
        'name': 'Review Provider', 'model': 'review-model',
        'base_url': 'https://api.example.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }


def enabled(specialist=True):
    return Settings(acceptance_gate_v1=True, specialist_workers_v1=specialist)


def test_review_is_opt_in_and_cannot_override_failed_release(monkeypatch):
    user_id = 960500
    project_id = verification_project(user_id, [dummy_check('failed')])
    Client.response = Response(json.dumps({
        'summary': 'Approve anyway',
        'suggestions': [{'title': 'Override failure', 'detail': 'Publish despite failing tests',
                         'severity': 'high', 'target': 'security.dummy'}],
    }))
    Client.calls = 0
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_kwargs: Client())
    without_review = asyncio.run(verify_package(
        user_id, project_id, 1, config=enabled(), provider=provider(),
    ))
    assert 'review' not in without_review and Client.calls == 0
    report = asyncio.run(verify_package(
        user_id, project_id, 1, config=enabled(), provider=provider(), include_review=True,
    ))
    assert report['status'] == 'failed' and report['can_publish'] is False
    assert report['review']['status'] == 'completed' and report['review']['gating'] is False
    assert report['review']['summary'] == 'Approve anyway'
    assert Client.calls == 1
    with workspace_db(user_id) as db:
        stored = db.execute('''SELECT content FROM artifacts WHERE project_id=?
            AND path='acceptance/report.json' AND version=1''', (project_id,)).fetchone()
    assert 'review' not in json.loads(stored['content'])
    payload = verification_payload(user_id, project_id, 1)
    assert payload['verification']['review']['status'] == 'completed'
    assert payload['verification']['can_publish'] is False


def test_review_failure_does_not_change_passed_release(monkeypatch):
    user_id = 960501
    project_id = verification_project(user_id, [dummy_check()])
    Client.response = RuntimeError('review unavailable')
    Client.calls = 0
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_kwargs: Client())
    report = asyncio.run(verify_package(
        user_id, project_id, 1, config=enabled(), provider=provider(), include_review=True,
    ))
    assert report['status'] == 'passed' and report['can_publish'] is True
    assert report['review']['status'] == 'failed' and report['review']['gating'] is False
    assert 'review unavailable' in report['review']['error']


def test_local_and_disabled_review_are_explicit_and_non_gating():
    user_id = 960502
    project_id = verification_project(user_id, [dummy_check()])
    local = asyncio.run(verify_package(
        user_id, project_id, 1, config=enabled(), provider=None, include_review=True,
    ))
    assert local['can_publish'] is True
    assert local['review']['status'] == 'unavailable' and local['review']['gating'] is False
    disabled = asyncio.run(verify_package(
        user_id, project_id, 1, config=enabled(False), provider=provider(), include_review=True,
    ))
    assert disabled['can_publish'] is True
    assert disabled['review']['status'] == 'disabled' and disabled['review']['gating'] is False
