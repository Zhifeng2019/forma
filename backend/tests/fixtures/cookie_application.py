"""A small real cookie-auth application used by proxy and browser regressions."""

from app.backend_engine import default_requirements
from app.database import workspace_db


SOURCE = '''
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/api/health")
def health():
    return {"status": "ok"}

def authenticated(request):
    if request.cookies.get("app_session") != "fixture-session":
        raise HTTPException(401)

@app.post("/api/auth/login")
def login():
    response = JSONResponse({"ok": True})
    response.set_cookie("app_session", "fixture-session", domain="apps.localhost", path="/api/auth",
                        httponly=True, samesite="lax")
    response.set_cookie("csrf", "fixture-csrf", domain="apps.localhost", path="/api", samesite="lax")
    return response

@app.get("/api/auth/me")
def me(request: Request):
    authenticated(request)
    return {"role": "admin", "studio_cookie": request.cookies.get("studio_session"),
            "authorization": request.headers.get("authorization")}

@app.post("/api/auth/touch")
def touch(request: Request):
    authenticated(request)
    if request.headers.get("x-csrftoken") != request.cookies.get("csrf"):
        raise HTTPException(403)
    return {"ok": True}

@app.post("/api/auth/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("app_session", domain="apps.localhost", path="/api/auth")
    response.delete_cookie("csrf", domain="apps.localhost", path="/api")
    return response
'''

HTML = '''<!doctype html><html><head><title>Cookie login test</title></head><body>
<p id="status">Checking</p><button id="login">Log in</button><button id="logout">Log out</button>
<script>
async function check() {
  document.querySelector('#status').textContent = 'Checking';
  const response = await fetch('/api/auth/me');
  document.querySelector('#status').textContent = response.ok ? 'Signed in' : 'Guest';
}
document.querySelector('#login').onclick = async () => { await fetch('/api/auth/login', {method:'POST'}); await check(); };
document.querySelector('#logout').onclick = async () => { await fetch('/api/auth/logout', {method:'POST'}); await check(); };
check();
</script></body></html>'''


def install_cookie_application(user_id, project_id):
    with workspace_db(user_id) as db:
        db.execute('INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)',
                   (project_id, 1, 'Cookie login', 'fastapi', 'single-file'))
        for path, content in {'index.html': HTML, 'backend/main.py': SOURCE,
                              'backend/requirements.txt': default_requirements()}.items():
            db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'build', path, content, 1))
        db.execute("UPDATE projects SET current_version=1,phase_index=1,backend_mode='fastapi',stage='review',stage_index=4 WHERE id=?",
                   (project_id,))
