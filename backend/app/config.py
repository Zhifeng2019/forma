from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    data_dir: str = str(ROOT / 'data')
    secret_key: str = 'forma-local-development-secret-change-in-production'
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    access_token_days: int = 14

    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / 'users').mkdir(exist_ok=True)
        (path / 'projects').mkdir(exist_ok=True)
        return path


settings = Settings()
