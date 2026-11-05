from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Status(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadRequest(BaseModel):
    url: HttpUrl = Field(max_length=8192)
    title: str = Field(default="", max_length=160)

    @field_validator("url")
    @classmethod
    def reject_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("URLs containing credentials are not supported.")
        return value

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return value.strip()


class Download(BaseModel):
    id: str
    url: str
    title: str
    filename: str
    headers: dict[str, str] = Field(default_factory=dict)
    provider: dict[str, str] = Field(default_factory=dict)
    etag: str = ""
    last_modified: str = ""
    status: Status = Status.QUEUED
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bytes: float = 0
    error: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def progress(self) -> float | None:
        if self.status == Status.COMPLETED:
            return 100
        if not self.total_bytes:
            return None
        return round(min(100, self.downloaded_bytes / self.total_bytes * 100), 1)

    def public(self) -> dict:
        # Signed source URLs can contain secrets; they stay in local storage.
        return self.model_dump(
            mode="json", exclude={"url", "headers", "provider", "etag", "last_modified"}
        ) | {"progress": self.progress}
