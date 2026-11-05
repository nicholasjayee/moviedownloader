import pytest

from moviebox_app.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        download_dir=tmp_path / "downloads",
        concurrency=1,
        max_queue=2,
        max_file_bytes=1024 * 1024,
    )
