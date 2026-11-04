from fastapi import Depends, HTTPException, Header
from .database import control_db, workspace_for
from .security import decode_session
from .user_activity import track_user_activity


async def current_user(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Sign in to continue')
    try:
        session = decode_session(authorization[7:])
        user_id = int(session['sub'])
    except Exception as exc:
        raise HTTPException(401, 'Your session has expired') from exc
    track_user_activity(user_id)
    with control_db() as db:
        user = db.execute('SELECT id,email,phone,name,role,status,created_at,session_version FROM users WHERE id=?', (user_id,)).fetchone()
    if not user or user['status'] != 'active' or session.get('sv', 0) != user['session_version']:
        raise HTTPException(401, 'This account is not active')
    workspace_for(user_id)
    return dict(user)


async def admin_user(user=Depends(current_user)):
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
