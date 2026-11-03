from pathlib import Path
import ipaddress
import re
from urllib.parse import urlsplit
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


def normalized_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('Studio, CORS, and application URLs must be explicit HTTP(S) origins')
    host = parsed.hostname.encode('idna').decode('ascii')
    if ':' in host:
        host = f'[{ipaddress.IPv6Address(host)}]'
    elif not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host):
        raise ValueError('Invalid origin hostname')
    port = parsed.port
    suffix = f':{port}' if port and port != (443 if parsed.scheme == 'https' else 80) else ''
    return f'{parsed.scheme}://{host}{suffix}'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    data_dir: str = str(ROOT.parent / 'data')
    secret_key: str = 'forma-local-development-secret-change-in-production'
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    studio_base_url: str = 'http://127.0.0.1:8000'
    # Wildcard host reserved for generated applications, never studio routes.
    apps_base_url: str = 'http://apps.localhost:8000'
    preview_token_minutes: int = 15
    access_token_days: int = 14
    runtime_python: str = ''
    runtime_pip_index_url: str = 'https://mirrors.aliyun.com/pypi/simple/'
    runtime_npm_registry: str = 'https://registry.npmmirror.com'
    runtime_build_timeout: int = 240
    # Builds and installs still making progress may continue past their timeout up to this limit.
    runtime_build_max_timeout: int = 900
    runtime_install_timeout: int = 240
    runtime_start_timeout: int = 25
    runtime_request_timeout: int = 20
    runtime_memory_mb: int = 768
    runtime_idle_seconds: int = 1800
    runtime_max_processes: int = 8
    durable_jobs_v1: bool = False
    acceptance_gate_v1: bool = False
    sandbox_v1: bool = False

    @model_validator(mode='after')
    def isolated_application_origins(self):
        self.studio_base_url = normalized_origin(self.studio_base_url)
        self.apps_base_url = normalized_origin(self.apps_base_url)
        self.cors_origins = ','.join(normalized_origin(value) for value in self.cors_origins.split(','))
        apps_host = urlsplit(self.apps_base_url).hostname
        if ':' in apps_host or apps_host.replace('.', '').isdigit():
            raise ValueError('APPS_BASE_URL requires a DNS hostname with wildcard subdomains')
        for origin in [self.studio_base_url, *self.cors_origins.split(',')]:
            host = urlsplit(origin.strip()).hostname
            if host == apps_host or host.endswith('.' + apps_host):
                raise ValueError('The application domain must be separate from every studio origin')
        if not 1 <= self.preview_token_minutes <= 60:
            raise ValueError('PREVIEW_TOKEN_MINUTES must be between 1 and 60')
        return self

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


settings = Settings()
