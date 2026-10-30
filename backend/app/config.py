import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    data_dir: str = str(ROOT.parent / 'data')
    secret_key: str = 'forma-local-development-secret-change-in-production'
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    studio_base_url: str = 'http://127.0.0.1:8000'
    access_token_days: int = 14
    runtime_python: str = ''
    runtime_pip_index_url: str = 'https://mirrors.aliyun.com/pypi/simple/'
    runtime_npm_registry: str = 'https://registry.npmmirror.com'
    runtime_build_timeout: int = 240
    runtime_install_timeout: int = 240
    runtime_start_timeout: int = 25
    runtime_request_timeout: int = 20
    runtime_memory_mb: int = 768
    runtime_idle_seconds: int = 1800
    runtime_max_processes: int = 8
    durable_jobs_v1: bool = False
    sandbox_v1: bool = False

    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir).expanduser()
        if not path.is_absolute():
            path = ROOT.parent / path
        path = path.resolve()
        legacy_path = (ROOT / 'data').resolve()
        if path == legacy_path:
            path = (ROOT.parent / 'data').resolve()
        path.mkdir(parents=True, exist_ok=True)
        (path / 'users').mkdir(exist_ok=True)
        (path / 'projects').mkdir(exist_ok=True)
        return path


# Package installers may need the host's proxy and CA settings. Only these variables are passed
# through, and only to npm/pip installation steps, never to generated application processes.
INSTALLER_NETWORK_VARIABLES = (
    'HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'NO_PROXY', 'no_proxy',
    'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'PIP_CERT', 'NODE_EXTRA_CA_CERTS', 'NPM_CONFIG_CAFILE',
)


def installer_network_environment() -> dict[str, str]:
    return {name: os.environ[name] for name in INSTALLER_NETWORK_VARIABLES if os.environ.get(name)}


def installer_ca_bundle() -> str | None:
    for name in ('PIP_CERT', 'REQUESTS_CA_BUNDLE', 'SSL_CERT_FILE'):
        if os.environ.get(name):
            return os.environ[name]
    return None


settings = Settings()
