"""Exercise preview credentials through the same authenticated exchange as the UI."""


def open_preview(client, project_id, token, version=None):
    response = client.post(f'/api/projects/{project_id}/preview-session',
                           params={'version': version} if version is not None else {},
                           headers={'Authorization': f'Bearer {token}'})
    if response.status_code != 200:
        return response
    return client.get(response.json()['url'])
