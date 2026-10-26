"""Deterministic FastAPI and SQLite source synthesis from an entity contract."""

from .contract import EntityContract
from .types import EntityFieldSpec

_PY_TYPES = {
    'string': 'str', 'text': 'str', 'uuid': 'str', 'date': 'str', 'datetime': 'str',
    'integer': 'int', 'number': 'float', 'boolean': 'bool',
}
_SQL_TYPES = {
    'string': 'TEXT', 'text': 'TEXT', 'uuid': 'TEXT', 'date': 'TEXT', 'datetime': 'TEXT',
    'integer': 'INTEGER', 'number': 'REAL', 'boolean': 'INTEGER',
}


def _model_field(field: EntityFieldSpec, patch: bool = False) -> str:
    optional = patch or not field.required
    annotation = _PY_TYPES[field.kind] + (' | None' if optional else '')
    arguments = []
    if optional:
        arguments.append('default=None')
    constraints = dict(field.constraints)
    if field.kind in {'string', 'text'} and field.required and not patch:
        constraints.setdefault('minLength', 1)
    for source, target in (('minLength', 'min_length'), ('maxLength', 'max_length'),
                           ('minimum', 'ge'), ('maximum', 'le')):
        if source in constraints:
            arguments.append(f'{target}={constraints[source]!r}')
    suffix = f' = Field({", ".join(arguments)})' if arguments else ''
    return f'    {field.name}: {annotation}{suffix}'


def _models_body(contract: EntityContract) -> str:
    name = contract.entity.name
    create_fields = '\n'.join(_model_field(field) for field in contract.fields)
    patch_fields = '\n'.join(_model_field(field, patch=True) for field in contract.fields)
    return f'''class {name}Input(BaseModel):
{create_fields}

class {name}Patch(BaseModel):
{patch_fields}
'''


def _sample_value(field: EntityFieldSpec) -> object:
    if field.kind in {'string', 'text'}:
        return f'Example {field.name.replace("_", " ")}'
    if field.kind == 'boolean':
        return 0
    if field.kind in {'integer', 'number'}:
        return 0
    if field.kind == 'uuid':
        return 'sample-1'
    return '2026-01-01'


def _database_body(contract: EntityContract) -> str:
    table = contract.collection
    columns = ', '.join(
        f'{field.name} {_SQL_TYPES[field.kind]}' + (' NOT NULL' if field.required else '')
        for field in contract.fields
    )
    names = ','.join(field.name for field in contract.fields)
    placeholders = ','.join('?' for _ in contract.fields)
    sample = tuple(_sample_value(field) for field in contract.fields)
    return f'''DATABASE = "app.db"

@contextmanager
def database():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize():
    with database() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {columns}
        )""")
        if connection.execute("SELECT COUNT(*) FROM {table}").fetchone()[0] == 0:
            connection.execute(
                "INSERT INTO {table}({names}) VALUES({placeholders})",
                {sample!r},
            )
'''


def _api_body(contract: EntityContract, product_name: str) -> str:
    entity = contract.entity.name
    table = contract.collection
    collection_path = contract.collection_path
    detail_path = contract.detail_path
    parameter = contract.path_parameter
    columns = ','.join(field.name for field in contract.fields)
    placeholders = ','.join('?' for _ in contract.fields)
    body_values = ', '.join(f'body.{field.name}' for field in contract.fields)
    required_strings = [field for field in contract.fields if field.required and field.kind in {'string', 'text'}]
    validation = '\n'.join(
        f'    if not str(body.{field.name}).strip():\n'
        f'        raise HTTPException(422, "{field.name} is required")'
        for field in required_strings
    )
    patch_validation = '\n'.join(
        f'    if "{field.name}" in values and values["{field.name}"] is None:\n'
        f'        raise HTTPException(422, "{field.name} is required")'
        + (
            f'\n    if "{field.name}" in values and not values["{field.name}"]:\n'
            f'        raise HTTPException(422, "{field.name} is required")'
            if field.kind in {'string', 'text'} else ''
        )
        for field in contract.fields if field.required
    )
    boolean_conversions = '\n'.join(
        f'    if result.get("{field.name}") is not None:\n'
        f'        result["{field.name}"] = bool(result["{field.name}"])'
        for field in contract.fields if field.kind == 'boolean'
    )
    serialization = (
        'def serialize(row):\n'
        '    result = dict(row)\n'
        f'{boolean_conversions}\n'
        '    return result\n'
    )
    optional_get = ''
    if ('GET', detail_path) in contract.operations:
        optional_get = f'''

@app.get("{detail_path}")
def get_{table}({parameter}: int):
    with database() as connection:
        row = connection.execute("SELECT * FROM {table} WHERE id=?", ({parameter},)).fetchone()
    if not row:
        raise HTTPException(404, "Item not found")
    return serialize(row)
'''
    return f'''
{serialization}
@asynccontextmanager
async def lifespan(_app):
    initialize()
    yield

app = FastAPI(title={product_name!r}, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/api/health")
def health():
    return {{"status": "ok", "service": {product_name!r}}}

@app.get("{collection_path}")
def list_{table}():
    with database() as connection:
        rows = connection.execute("SELECT * FROM {table} ORDER BY id DESC").fetchall()
    return {{"{table}": [serialize(row) for row in rows]}}

@app.post("{collection_path}", status_code=201)
def create_{table}(body: {entity}Input):
{validation or '    pass'}
    with database() as connection:
        cursor = connection.execute(
            "INSERT INTO {table}({columns}) VALUES({placeholders})",
            ({body_values},),
        )
        row = connection.execute("SELECT * FROM {table} WHERE id=?", (cursor.lastrowid,)).fetchone()
    return serialize(row)
{optional_get}
@app.patch("{detail_path}")
def update_{table}({parameter}: int, body: {entity}Patch):
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(400, "No changes supplied")
    for key, value in values.items():
        if isinstance(value, str):
            values[key] = value.strip()
{patch_validation}
    with database() as connection:
        assignments = ','.join(f'{{key}}=?' for key in values)
        cursor = connection.execute(
            f"UPDATE {table} SET {{assignments}} WHERE id=?",
            [*values.values(), {parameter}],
        )
        if not cursor.rowcount:
            raise HTTPException(404, "Item not found")
        row = connection.execute("SELECT * FROM {table} WHERE id=?", ({parameter},)).fetchone()
    return serialize(row)

@app.delete("{detail_path}", status_code=204)
def delete_{table}({parameter}: int):
    with database() as connection:
        cursor = connection.execute("DELETE FROM {table} WHERE id=?", ({parameter},))
        if not cursor.rowcount:
            raise HTTPException(404, "Item not found")
'''


def backend_sources(contract: EntityContract, product_name: str, source_format: str) -> dict[str, str]:
    models = _models_body(contract)
    database = _database_body(contract)
    api = _api_body(contract, product_name)
    if source_format == 'single-file':
        source = (
            'from contextlib import asynccontextmanager, contextmanager\n'
            'import sqlite3\n'
            'from fastapi import FastAPI, HTTPException\n'
            'from pydantic import BaseModel, Field\n\n'
            f'{models}\n{database}\n{api}'
        )
        return {'backend/main.py': source}
    return {
        'backend/main.py': 'from app.api import app\n',
        'backend/app/__init__.py': '"""Generated application backend."""\n',
        'backend/app/models.py': f'from pydantic import BaseModel, Field\n\n{models}',
        'backend/app/database.py': f'from contextlib import contextmanager\nimport sqlite3\n\n{database}',
        'backend/app/api.py': (
            'from contextlib import asynccontextmanager\n'
            'from fastapi import FastAPI, HTTPException\n'
            'from .database import database, initialize\n'
            f'from .models import {contract.entity.name}Input, {contract.entity.name}Patch\n\n{api}'
        ),
    }
