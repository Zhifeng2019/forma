import sqlite3


def database():
    db = sqlite3.connect('app.db')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, title TEXT NOT NULL)')
    db.commit()
    return db
