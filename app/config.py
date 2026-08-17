"""Application paths and defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DOWNLOAD_DIR = PROJECT_ROOT / "downloads"
VENDOR_YTDLP = PROJECT_ROOT / "vendor" / "yt-dlp"


@dataclass(slots=True)
class AppSettings:
    download_folder: str = str(DOWNLOAD_DIR)
    quality: str = "best"
    audio_format: str = "mp3"
    container: str = "auto"
    subtitles: bool = False
    thumbnail: bool = False
    embed_metadata: bool = True
    output_template: str = "%(uploader)s/%(title)s [%(id)s].%(ext)s"
    concurrent_downloads: int = 2
    rate_limit: str = ""
    retries: int = 3
    browser: str = ""
    archive_file: str = str(DATA_DIR / "downloaded.txt")
    use_archive: bool = True
    max_results: int = 1000
    socket_timeout: int = 30

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> AppSettings:
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
