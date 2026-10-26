from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    data_dir: str = str(ROOT.parent / 'data')
    secret_key: str = 'forma-local-development-secret-change-in-production'
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
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
    appspec_v1: bool = False
    acceptance_gate_v1: bool = False
    specialist_workers_v1: bool = False
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


settings = Settings()
