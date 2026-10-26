"""Feature-gated AppSpec services used by the generation engine."""

import json

from ..config import Settings
from ..features import FeatureFlag, require_feature
from .compiler import CompiledPackage, compile_package
from .legacy_adapter import legacy_appspec
from .schema import APPSPEC_PATH, BUILD_MANIFEST_PATH, appspec_document


def compile_legacy_package(
    project: dict,
    source_files: dict[str, str],
    config: Settings | None = None,
) -> CompiledPackage:
    require_feature(FeatureFlag.APPSPEC_V1, config)
    return compile_package(legacy_appspec(project, source_files), source_files)


def spec_artifacts(compiled: CompiledPackage) -> dict[str, str]:
    return {
        APPSPEC_PATH: appspec_document(compiled.spec),
        BUILD_MANIFEST_PATH: json.dumps(compiled.manifest, indent=2, sort_keys=True, ensure_ascii=False) + '\n',
    }
