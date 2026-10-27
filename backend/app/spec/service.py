"""Feature-gated AppSpec services used by the generation engine."""

import json

from ..config import Settings
from ..features import FeatureFlag, require_feature
from .compiler import CompiledPackage, compile_package
from .generator import propose_appspec
from .legacy_adapter import legacy_appspec
from .schema import APPSPEC_PATH, BUILD_MANIFEST_PATH, appspec_document
from ..verification.manifest import acceptance_artifacts


def compile_legacy_package(
    project: dict,
    source_files: dict[str, str],
    config: Settings | None = None,
) -> CompiledPackage:
    require_feature(FeatureFlag.APPSPEC_V1, config)
    return compile_package(legacy_appspec(project, source_files), source_files)


async def generate_appspec_package(
    project: dict,
    provider: dict | None,
    phase: int,
    feedback: str = '',
    current_spec=None,
    brief: str | None = None,
    config: Settings | None = None,
) -> CompiledPackage:
    require_feature(FeatureFlag.APPSPEC_V1, config)
    project = dict(project)
    spec = await propose_appspec(
        provider, project['name'], brief or project['brief'], project['source_format'],
        project['backend_mode'], phase, feedback, current_spec,
    )
    return compile_package(spec, phase=phase)


def spec_artifacts(compiled: CompiledPackage) -> dict[str, str]:
    artifacts = {
        APPSPEC_PATH: appspec_document(compiled.spec),
        BUILD_MANIFEST_PATH: json.dumps(compiled.manifest, indent=2, sort_keys=True, ensure_ascii=False) + '\n',
    }
    artifacts.update(acceptance_artifacts(compiled))
    return artifacts
