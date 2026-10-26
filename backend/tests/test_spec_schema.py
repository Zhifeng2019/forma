import copy
import json
from pathlib import Path

import pytest

from app.spec.schema import AppSpecError, appspec_document, appspec_hash, parse_appspec

FIXTURE = Path(__file__).parent / 'fixtures' / 'appspec' / 'item_manager.json'


def fixture_document() -> dict:
    return json.loads(FIXTURE.read_text())


def test_versioned_schema_covers_the_complete_contract():
    spec = parse_appspec(fixture_document())
    assert spec.schema_version == '1.0' and spec.compiler_version == '1.0'
    assert spec.product.name == 'Item Manager'
    assert spec.architecture.state_ownership == 'server'
    assert spec.entities[0].fields[1].constraints['maxLength'] == 160
    assert spec.api[1].entity == 'Item'
    assert spec.frontend.state_adapter == 'forma-api'
    assert len(spec.manifest.files) == 14
    assert len(spec.acceptance) == 3
    assert len(appspec_hash(spec)) == 64
    envelope = json.loads(appspec_document(spec))
    assert envelope['spec_hash'] == appspec_hash(spec)
    assert envelope['spec']['product']['name'] == 'Item Manager'


@pytest.mark.parametrize('mutation, match', [
    (lambda doc: doc['api'][1].update(entity='Missing'), 'unknown entity Missing'),
    (lambda doc: doc['entities'][0]['relationships'].append('Missing'), 'unknown entities: Missing'),
    (lambda doc: doc['api'].append({'name': 'Duplicate', 'method': 'GET', 'path': '/api/items'}),
     'Duplicate API operation'),
    (lambda doc: doc['acceptance'].append({'name': 'Unknown', 'kind': 'api', 'target': '/api/missing'}),
     'unknown API path'),
    (lambda doc: doc['dependencies']['python'].append('httpx==1.0'), 'unversioned reviewed package'),
    (lambda doc: doc['manifest']['generation_order'].append('frontend/src/Missing.jsx'),
     'undeclared paths'),
    (lambda doc: doc['frontend'].update(state_adapter='browser-local'), 'requires the forma-api'),
])
def test_invalid_cross_contract_references_fail_before_compilation(mutation, match):
    document = fixture_document()
    mutation(document)
    with pytest.raises(AppSpecError, match=match):
        parse_appspec(document)


def test_schema_rejects_unknown_fields_and_duplicate_manifest_paths():
    document = fixture_document()
    document['unexpected'] = True
    with pytest.raises(AppSpecError, match='unexpected'):
        parse_appspec(document)
    document = fixture_document()
    document['manifest']['files'].append(copy.deepcopy(document['manifest']['files'][0]))
    with pytest.raises(AppSpecError, match='duplicate paths'):
        parse_appspec(document)
