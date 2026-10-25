from fastapi import Depends, HTTPException, Header
from .database import control_db, workspace_for
from .security import decode_token


def current_user(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Sign in to continue')
    try:
        user_id = decode_token(authorization[7:])
    except Exception as exc:
        raise HTTPException(401, 'Your session has expired') from exc
    with control_db() as db:
        user = db.execute('SELECT id,email,name,role,status,created_at FROM users WHERE id=?', (user_id,)).fetchone()
    if not user or user['status'] != 'active':
        raise HTTPException(401, 'This account is not active')
    workspace_for(user_id)
    return dict(user)


def admin_user(user=Depends(current_user)):
    if user['role'] != 'admin':
        raise HTTPException(403, 'Administrator access required')
    return user


def owned_project(user_id: int, project_id: str):
    from .database import workspace_db
    with workspace_db(user_id) as db:
        project = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
    if not project:
        raise HTTPException(404, 'Project not found')
    return project
