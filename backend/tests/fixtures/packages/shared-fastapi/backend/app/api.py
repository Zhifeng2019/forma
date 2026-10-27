from contextlib import closing

from fastapi import FastAPI

from app.database import database
from app.models import ItemInput

app = FastAPI()


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.get('/api/items')
def items():
    with closing(database()) as db:
        rows = db.execute('SELECT id,title FROM items ORDER BY id DESC').fetchall()
    return {'items': [dict(row) for row in rows]}


@app.post('/api/items', status_code=201)
def create_item(body: ItemInput):
    with closing(database()) as db:
        cursor = db.execute('INSERT INTO items(title) VALUES(?)', (body.title.strip(),))
        db.commit()
        item_id = cursor.lastrowid
    return {'id': item_id, 'title': body.title.strip()}
