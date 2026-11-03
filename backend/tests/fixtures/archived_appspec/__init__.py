"""Frozen output of the retired compiler, used only to test historical compatibility.

These fixtures were captured before removal. Loading them never generates application
source. Hash checks detect accidental changes to the archived source or contract.
"""

from dataclasses import dataclass
import json
from pathlib import Path

from app.jobs.idempotency import canonical_input_hash
from app.spec.schema import appspec_document, appspec_hash, parse_appspec
from app.spec.types import AppSpec
from app.verification.manifest import acceptance_artifacts


@dataclass
class ArchivedPackage:
    spec: AppSpec
    files: dict[str, str]
    manifest: dict
    spec_hash: str
    source_hash: str


def archived_package(source_format='multi-file', backend_mode='static', phase=2, *, fixture=None, brief=None):
    key = fixture or f'{source_format}-{backend_mode}-phase{phase}'
    document = json.loads(Path(__file__).with_name(f'{key}.json').read_text())
    spec = parse_appspec(document['spec'])
    assert appspec_hash(spec) == document['spec_hash'], key
    assert canonical_input_hash(document['files']) == document['source_hash'], key
    if brief is not None:
        spec = spec.model_copy(update={'product': spec.product.model_copy(update={
            'brief': brief, 'primary_workflow': brief,
        })})
    return ArchivedPackage(spec, document['files'], document['manifest'], appspec_hash(spec), document['source_hash'])


def spec_artifacts(package):
    return {
        'appspec.json': appspec_document(package.spec),
        'build-manifest.json': json.dumps(package.manifest, sort_keys=True),
        **acceptance_artifacts(package),
    }
