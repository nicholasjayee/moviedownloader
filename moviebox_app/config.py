from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOVIEBOX_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost", "[::1]"])
    port: int = Field(default=8765, ge=1, le=65535)
    data_dir: Path = Path("data")
    download_dir: Path = Path("downloads")
    concurrency: int = Field(default=3, ge=1, le=16)
    max_queue: int = Field(default=100, ge=1, le=1000)
    max_file_bytes: int = Field(default=20 * 1024**3, ge=1)
    chunk_size: int = Field(default=256 * 1024, ge=1024, le=1024 * 1024)
    connect_timeout: float = Field(default=15, gt=0)
    read_timeout: float = Field(default=45, gt=0)
    catalog_api_base: str = "https://h5-api.aoneroom.com/wefeed-h5api-bff"
    catalog_host: str = "moviebox.ph"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "moviebox.sqlite3"
