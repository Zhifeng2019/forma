"""Approved accounts for non-registration tests; never a production auth bypass.

Registration's delivery, verification and approval flow has its own API tests.
Other feature tests provision an account directly and exercise normal sign-in.
"""
from app.database import control_db, workspace_for
from app.security import hash_password


def register_account(client, *, json):
    with control_db() as db:
        cursor = db.execute('''INSERT INTO users(email,name,password_hash,status,verified_at)
            VALUES(?,?,?,'active',CURRENT_TIMESTAMP)''',
            (json['email'].lower(), json['name'], hash_password(json['password'])))
        db.execute('INSERT INTO preferences(user_id) VALUES(?)', (cursor.lastrowid,))
        user_id = cursor.lastrowid
    workspace_for(user_id)
    return client.post('/api/auth/login', json={'email': json['email'], 'password': json['password']})
