import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mpeg", ".mpg", ".ts"}


def source_name(url: str, title: str) -> tuple[str, str]:
    source = Path(unquote(urlsplit(url).path)).name
    suffix = Path(source).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        suffix = ".mp4"
    display = title or Path(source).stem or "Untitled movie"
    safe = re.sub(r"[^\w .()-]", "_", display, flags=re.UNICODE).strip(" .")[:120]
    safe = safe.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .")
    return display, (safe or "movie") + suffix


def job_path(directory: Path, job_id: str, filename: str, *, partial: bool = False) -> Path:
    # IDs are generated internally; source filenames never become directory paths.
    path = directory / f"{job_id}_{Path(filename).name}"
    return path.with_name(path.name + ".part") if partial else path
