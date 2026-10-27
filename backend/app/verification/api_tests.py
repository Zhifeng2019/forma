"""Generate executable API and persistence checks from AppSpec operations."""

from .common import (
    GeneratedCheck, HTTP_HELPERS, AcceptanceContext, create_payload, detail_script,
    patch_payload, required_string,
)


def generate_api_tests(context: AcceptanceContext) -> tuple[dict[str, str], list[GeneratedCheck]]:
    spec = context.spec
    if spec.architecture.backend_mode == 'static':
        return {'acceptance/api_tests.py': '# No backend API operations are declared for this frontend-only AppSpec.\n'}, []
    contract = context.contract
    constants = ''
    methods = []
    checks = []
    operations = {(operation.method, operation.path) for operation in spec.api}
    if ('GET', '/api/health') in operations:
        methods.append('''    def test_health(self):
        status, _body = request('GET', '/api/health')
        self.assertEqual(status, 200)
''')
        checks.append(GeneratedCheck('api.health', 'api', '/api/health', 'test_health',
                                     'acceptance/api_tests.py', environment=('APP_BASE_URL',)))
    if contract:
        created = create_payload(contract)
        patched = patch_payload(contract, created)
        constants = (
            f'COLLECTION_PATH = {contract.collection_path!r}\n'
            f'COLLECTION_KEY = {contract.collection!r}\n'
            f'CREATE_PAYLOAD = {created!r}\n'
            f'PATCH_PAYLOAD = {patched!r}\n'
            f'{detail_script(contract)}\n'
        )
        detail_get = ''
        if ('GET', contract.detail_path) in contract.operations:
            detail_get = '''        status, _body = request('GET', detail_url(record_id))
        self.assertEqual(status, 200)
'''
        methods.append(f'''    def test_crud(self):
        record_id = None
        try:
            status, created = request('POST', COLLECTION_PATH, CREATE_PAYLOAD)
            self.assertEqual(status, 201, created)
            record_id = created['id']
            status, updated = request('PATCH', detail_url(record_id), PATCH_PAYLOAD)
            self.assertEqual(status, 200, updated)
            for key, expected in PATCH_PAYLOAD.items():
                self.assertEqual(updated[key], expected)
{detail_get}            status, listing = request('GET', COLLECTION_PATH)
            self.assertEqual(status, 200)
            self.assertTrue(any(row['id'] == record_id for row in listing[COLLECTION_KEY]))
        finally:
            if record_id is not None:
                request('DELETE', detail_url(record_id))
''')
        checks.append(GeneratedCheck('api.crud', 'api', contract.collection_path, 'test_crud',
                                     'acceptance/api_tests.py', mutates=True, environment=('APP_BASE_URL',)))
        required = required_string(contract)
        if required:
            methods.append(f'''    def test_required_validation(self):
        payload = dict(CREATE_PAYLOAD)
        payload[{required.name!r}] = ' '
        status, _body = request('POST', COLLECTION_PATH, payload)
        self.assertIn(status, {{400, 422}})
''')
            checks.append(GeneratedCheck('api.required-validation', 'validation', required.name,
                                         'test_required_validation', 'acceptance/api_tests.py',
                                         mutates=True, environment=('APP_BASE_URL',)))
        methods.append('''    def test_restart_persistence(self):
        record_id = None
        try:
            status, created = request('POST', COLLECTION_PATH, CREATE_PAYLOAD)
            self.assertEqual(status, 201, created)
            record_id = created['id']
            restart_url = os.environ.get('APP_RESTART_URL', '')
            if not restart_url:
                raise RuntimeError('APP_RESTART_URL is required for restart persistence')
            status, _body = request('POST', '', raw_url=restart_url, studio=True)
            self.assertEqual(status, 200, _body)
            status, listing = request('GET', COLLECTION_PATH)
            self.assertEqual(status, 200)
            self.assertTrue(any(row['id'] == record_id for row in listing[COLLECTION_KEY]))
        finally:
            if record_id is not None:
                request('DELETE', detail_url(record_id))
''')
        checks.append(GeneratedCheck('persistence.restart', 'persistence', 'app.db',
                                     'test_restart_persistence', 'acceptance/api_tests.py', timeout=90,
                                     mutates=True, environment=('APP_BASE_URL', 'APP_RESTART_URL')))
    source = (
        '"""Generated from AppSpec. No model review is used for acceptance."""\n'
        'import os\nimport unittest\n\n'
        f'{HTTP_HELPERS}\n{constants}\n'
        'class AcceptanceTests(unittest.TestCase):\n'
        + ('\n'.join(methods) if methods else '    pass\n')
        + "\n\nif __name__ == '__main__':\n    unittest.main()\n"
    )
    return {'acceptance/api_tests.py': source}, checks
