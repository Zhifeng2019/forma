"""Assemble deterministic acceptance artifacts and provenance manifests."""

import json

from ..spec.capabilities import assess_capabilities
from ..spec.compiler import CompiledPackage
from ..spec.schema import APPSPEC_SCHEMA_VERSION, COMPILER_VERSION
from .api_tests import generate_api_tests
from .browser_tests import generate_browser_tests
from .common import AcceptanceContext, GeneratedCheck
from .migration_tests import generate_migration_tests
from .security_tests import generate_security_tests


def acceptance_artifacts(compiled: CompiledPackage) -> dict[str, str]:
    generation = compiled.manifest.get('generation', {'mode': 'scoped-source'})
    context = AcceptanceContext(
        compiled.spec, compiled.source_hash, generation.get('phase', 1), compiled.files,
    )
    files = {}
    checks = []
    for generator in (generate_api_tests, generate_browser_tests, generate_security_tests, generate_migration_tests):
        generated, generated_checks = generator(context)
        files.update(generated)
        checks.extend(generated_checks)
    target = 'frontend/dist/index.html' if compiled.spec.architecture.source_format == 'multi-file' else 'index.html'
    checks.append(GeneratedCheck('build.production', 'build', target, 'ensure_frontend_build',
                                 'studio:frontend-build', environment=()))
    capability = assess_capabilities(compiled.spec) if context.contract else None
    if capability:
        checks.append(GeneratedCheck(
            'capability.declared-scope', 'capability', 'requested product scope',
            'evaluate requested capabilities', 'studio:capability-review', environment=(),
        ))
        files['acceptance/capabilities.json'] = json.dumps(capability, indent=2, sort_keys=True) + '\n'
    document = {
        'schema_version': APPSPEC_SCHEMA_VERSION,
        'compiler_version': COMPILER_VERSION,
        'spec_hash': compiled.spec_hash,
        'source_hash': compiled.source_hash,
        'generation': generation,
        'capability': capability,
        'declared_acceptance': [check.model_dump(mode='json') for check in compiled.spec.acceptance],
        'checks': [check.document() for check in sorted(checks, key=lambda item: item.check_id)],
    }
    files['acceptance/manifest.json'] = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    return files
