import time

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def register(email, name='Test User'):
    response = client.post('/api/auth/register', json={'email': email, 'name': name, 'password': 'password123'})
    assert response.status_code == 200, response.text
    return response.json()


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def test_complete_product_lifecycle():
    account = register('maker@example.com')
    token = account['token']
    response = client.post('/api/projects', headers=auth(token), json={
        'name': 'Client Compass',
        'brief': 'A client portal for a small consultancy to track project progress and next actions.',
        'auto_mode': False,
    })
    assert response.status_code == 200, response.text
    project = response.json()
    assert project['stage'] == 'design'
    assert project['artifacts'][0]['path'] == 'product.md'
    project_id = project['id']

    response = client.post(f'/api/projects/{project_id}/messages', headers=auth(token), json={'content': 'Keep the first release focused on one primary workflow.'})
    assert response.status_code == 200
    project = response.json()
    product = next(a['content'] for a in project['artifacts'] if a['path'] == 'product.md')
    assert 'Revision direction' in product

    for expected in ['plan', 'build', 'build', 'build', 'review']:
        response = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={'feedback': ''})
        assert response.status_code == 200, response.text
        project = response.json()
        assert project['stage'] == expected

    assert project['current_version'] == 3
    assert len(project['versions']) == 3
    assert '<html' in next(a['content'] for a in project['artifacts'] if a['path'] == 'index.html')

    response = client.post(f'/api/projects/{project_id}/messages', headers=auth(token), json={
        'content': 'Make the primary action more prominent.',
        'selection': {'selector': '#newItem', 'text': 'Create new item'},
    })
    assert response.status_code == 200
    project = response.json()
    assert project['current_version'] == 4
    assert 'Selected element: #newItem' in project['messages'][-2]['content']

    response = client.get(f'/api/projects/{project_id}/preview?access_token={token}')
    assert response.status_code == 200
    assert 'forma-picker' in response.text

    assert client.get(f'/apps/{project_id}/').status_code == 404
    response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
    assert response.status_code == 200
    assert response.json()['published_version'] == 4
    response = client.get(f'/apps/{project_id}/')
    assert response.status_code == 200
    assert 'Client Compass' in response.text

    other = register('other@example.com')
    assert client.get(f'/api/projects/{project_id}', headers=auth(other['token'])).status_code == 404
    assert client.get(f'/api/projects/{project_id}/preview?access_token={other["token"]}').status_code == 404


def test_admin_provider_and_user_controls():
    login = client.post('/api/auth/login', json={'email': 'admin@forma.local', 'password': 'admin123'})
    assert login.status_code == 200
    admin = login.json()
    response = client.post('/api/providers', headers=auth(admin['token']), json={
        'name': 'Test provider', 'base_url': 'https://api.example.com/v1',
        'model': 'test-model', 'api_key': 'secret-key', 'enabled': True,
    })
    assert response.status_code == 200
    provider_id = response.json()['id']
    providers = client.get('/api/providers', headers=auth(admin['token'])).json()
    provider = next(p for p in providers if p['id'] == provider_id)
    assert provider['has_key'] is True
    assert 'api_key_encrypted' not in provider
    users = client.get('/api/admin/users', headers=auth(admin['token'])).json()
    assert any(u['email'] == 'maker@example.com' for u in users)


def test_autopilot_reaches_review_without_manual_gates():
    account = register('auto@example.com')
    response = client.post('/api/projects', headers=auth(account['token']), json={
        'name': 'Autopilot App', 'brief': 'A simple focused application for tracking weekly creative work.',
        'auto_mode': True,
    })
    assert response.status_code == 200
    project = response.json()
    assert project['stage'] == 'review'
    assert project['current_version'] == 3


def test_deferred_autopilot_reaches_review_in_the_background():
    with TestClient(app) as live:
        response = live.post('/api/auth/register', json={
            'email': 'deferred@example.com', 'name': 'Deferred Maker', 'password': 'password123',
        })
        token = response.json()['token']
        response = live.post('/api/projects', headers=auth(token), json={
            'name': 'Live Autopilot', 'brief': 'A personal focus timer with a weekly overview and local browser state.',
            'auto_mode': True, 'backend_mode': 'static', 'defer': True,
        })
        assert response.status_code == 200, response.text
        project = response.json()
        assert project['status'] in {'working', 'ready'}
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            project = live.get(f'/api/projects/{project["id"]}', headers=auth(token)).json()
            if project['stage'] == 'review' or project['status'] == 'error':
                break
            time.sleep(0.05)
        assert project['status'] == 'ready', project['messages'][-1]['content']
        assert project['stage'] == 'review'
        assert project['current_version'] == 3


def test_feedback_refines_current_phase_without_advancing():
    account = register('feedback@example.com')
    response = client.post('/api/projects', headers=auth(account['token']), json={
        'name': 'Phase Feedback', 'brief': 'A personal reading list with notes and a calm weekly overview.',
        'backend_mode': 'static', 'auto_mode': False,
    })
    project = response.json()
    project_id = project['id']
    for _ in range(3):
        response = client.post(f'/api/projects/{project_id}/advance', headers=auth(account['token']), json={})
        project = response.json()
    assert project['stage'] == 'build'
    assert project['phase_index'] == 1
    assert project['current_version'] == 1

    response = client.post(f'/api/projects/{project_id}/messages', headers=auth(account['token']), json={
        'content': 'Keep this phase, but make the primary action calmer.',
    })
    assert response.status_code == 200, response.text
    project = response.json()
    assert project['stage'] == 'build'
    assert project['phase_index'] == 1
    assert project['current_version'] == 2
    assert project['versions'][0]['label'] == 'Refinement'
    assert project['messages'][-1]['content'] == 'Your feedback has been applied in a new version.'

    response = client.post(f'/api/projects/{project_id}/advance', headers=auth(account['token']), json={})
    project = response.json()
    assert project['stage'] == 'build'
    assert project['phase_index'] == 2
    assert project['current_version'] == 3


def test_deferred_document_build_and_feedback_actions_update_in_background():
    with TestClient(app) as live:
        response = live.post('/api/auth/register', json={
            'email': 'deferred-actions@example.com', 'name': 'Deferred Actions', 'password': 'password123',
        })
        token = response.json()['token']
        response = live.post('/api/projects', headers=auth(token), json={
            'name': 'Deferred Actions App', 'brief': 'A personal planning tool with a clear product document and weekly overview.',
            'backend_mode': 'static', 'auto_mode': False,
        })
        project = response.json()
        project_id = project['id']

        def wait_ready():
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                current = live.get(f'/api/projects/{project_id}', headers=auth(token)).json()
                if current['status'] != 'working':
                    return current
                time.sleep(0.05)
            raise AssertionError('Background generation did not finish')

        response = live.post(f'/api/projects/{project_id}/messages', headers=auth(token), json={
            'content': 'Add a concise release-safety section.', 'defer': True,
        })
        assert response.status_code == 200, response.text
        project = response.json()
        assert project['status'] == 'working' and project['current_version'] == 0
        assert project['messages'][-1]['role'] == 'user'
        project = wait_ready()
        assert project['status'] == 'ready' and project['stage'] == 'design'
        product = next(artifact['content'] for artifact in project['artifacts'] if artifact['path'] == 'product.md')
        assert 'release-safety section' in product

        for _ in range(2):
            response = live.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={})
            project = response.json()
        assert project['stage'] == 'build' and project['phase_index'] == 0
        response = live.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={'defer': True})
        assert response.status_code == 200, response.text
        project = response.json()
        assert project['status'] == 'working' and project['current_version'] == 0
        project = wait_ready()
        assert project['status'] == 'ready'
        assert project['current_version'] == 1 and project['phase_index'] == 1

        response = live.post(f'/api/projects/{project_id}/messages', headers=auth(token), json={
            'content': 'Refine this same phase with a calmer primary action.', 'defer': True,
        })
        assert response.status_code == 200, response.text
        project = response.json()
        assert project['status'] == 'working' and project['current_version'] == 1
        assert project['messages'][-1]['role'] == 'user'
        project = wait_ready()
        assert project['status'] == 'ready'
        assert project['current_version'] == 2 and project['phase_index'] == 1
        assert project['versions'][0]['label'] == 'Refinement'
        assert live.delete(f'/api/projects/{project_id}', headers=auth(token)).status_code == 200
