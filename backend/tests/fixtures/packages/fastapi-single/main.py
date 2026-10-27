from contextlib import closing
import sqlite3

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI()


class ItemInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)


def database():
    db = sqlite3.connect('app.db')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, title TEXT NOT NULL)')
    db.commit()
    return db


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
