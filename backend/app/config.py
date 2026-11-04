from pathlib import Path
import ipaddress
import json
import logging
import os
import re
from urllib.parse import urlsplit
from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / '.env'


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
    # The same absolute file is used from the repo root, backend, or development launcher.
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra='ignore')
    data_dir: str = str(ROOT.parent / 'data')
    secret_key: str = 'forma-local-development-secret-change-in-production'
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    studio_base_url: str = 'http://127.0.0.1:8000'
    studio_path_prefix: str = ''
    # Wildcard host reserved for generated applications, never studio routes.
    apps_base_url: str = 'http://apps.localhost:8000'
    preview_token_minutes: int = 15
    access_token_days: int = 14
    auth_email_delivery_enabled: bool = False
    smtp_host: str = ''
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_tls_mode: Literal['ssl', 'starttls'] = 'ssl'
    smtp_username: str = ''
    smtp_password: str = ''
    smtp_from_address: str = ''
    smtp_from_name: str = 'Forma Studio'
    auth_sms_delivery_enabled: bool = False
    alibaba_cloud_access_key_id: str = ''
    alibaba_cloud_access_key_secret: str = ''
    alibaba_cloud_security_token: str = ''
    aliyun_sms_sign_name: str = ''
    aliyun_sms_registration_template_code: str = ''
    aliyun_sms_password_reset_template_code: str = ''
    aliyun_sms_code_param: str = 'code'
    auth_delivery_transport_timeout_seconds: float = Field(default=15, ge=1, le=60, allow_inf_nan=False)
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
        self.studio_path_prefix = self.studio_path_prefix.strip().rstrip('/')
        if self.studio_path_prefix and not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)+', self.studio_path_prefix):
            raise ValueError('STUDIO_PATH_PREFIX must be empty or an absolute path such as /forma')
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


def configuration_report(config: Settings = settings, env_file: Path = ENV_FILE) -> dict:
    """A small allowlist of startup diagnostics; never include secret or provider values."""
    legacy_env = env_file.parent.parent / '.env'
    inherited = {key.lower() for key in os.environ}
    return {
        'environment_file': str(env_file),
        'environment_file_exists': env_file.is_file(),
        'studio_path_prefix': config.studio_path_prefix,
        'ignored_environment_files': [str(legacy_env)] if legacy_env.is_file() else [],
        'process_overrides': sorted(key.upper() for key in Settings.model_fields if key.lower() in inherited),
        'generation_path': 'llm-source (local demo when no model is selected)',
        'features': {key.upper(): getattr(config, key) for key in (
            'durable_jobs_v1', 'acceptance_gate_v1', 'sandbox_v1',
        )},
    }


def log_configuration() -> None:
    logger = logging.getLogger('uvicorn.error')
    report = configuration_report()
    logger.info('Forma configuration: %s', json.dumps(report, sort_keys=True))
    if report['ignored_environment_files']:
        logger.warning('Root .env is ignored. Keep settings in %s; process variables take precedence.', ENV_FILE)
