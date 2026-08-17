"""Download option construction and yt-dlp execution."""

from __future__ import annotations

import re
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.config import AppSettings
from app.services.link_parser import normalize_url
from app.services.ytdlp_loader import load_ytdlp

ProgressCallback = Callable[[dict[str, Any]], None]
LogCallback = Callable[[str, str], None]


class DownloadCancelled(RuntimeError):
    pass


def build_download_options(
    settings: AppSettings,
    progress_hook: ProgressCallback | None = None,
    logger: Any | None = None,
) -> dict[str, Any]:
    folder = Path(settings.download_folder).expanduser()
    output = str(folder / settings.output_template)
    options: dict[str, Any] = {
        "outtmpl": output,
        "continuedl": True,
        "retries": max(0, settings.retries),
        "fragment_retries": max(0, settings.retries),
        "socket_timeout": max(1, settings.socket_timeout),
        "noprogress": True,
        "ignoreerrors": False,
        "windowsfilenames": False,
        "writethumbnail": settings.thumbnail,
        "writesubtitles": settings.subtitles,
        "writeautomaticsub": False,
        "restrictfilenames": False,
    }
    postprocessors: list[dict[str, Any]] = []
    if settings.quality == "1080p":
        options["format"] = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
    elif settings.quality == "audio":
        options["format"] = "bestaudio/best"
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": settings.audio_format,
                "preferredquality": "0",
            }
        )
    else:
        options["format"] = "bestvideo+bestaudio/best"
    if settings.container != "auto" and settings.quality != "audio":
        options["merge_output_format"] = settings.container
    if settings.rate_limit.strip():
        options["ratelimit"] = _parse_byte_rate(settings.rate_limit)
    if settings.embed_metadata:
        postprocessors.append(
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
                "add_chapters": True,
                "add_infojson": None,
            }
        )
    if postprocessors:
        options["postprocessors"] = postprocessors
    if settings.use_archive and settings.archive_file.strip():
        options["download_archive"] = str(Path(settings.archive_file).expanduser())
    if settings.browser:
        options["cookiesfrombrowser"] = (settings.browser,)
    if progress_hook:
        options["progress_hooks"] = [progress_hook]
        options["postprocessor_hooks"] = [progress_hook]
    if logger:
        options["logger"] = logger
    return options


def download_url(
    url: str,
    settings: AppSettings,
    cancel_event: threading.Event,
    progress: ProgressCallback,
    log: LogCallback,
) -> None:
    normalized = normalize_url(url)
    if not normalized:
        raise ValueError("Invalid HTTP or HTTPS URL.")
    folder = Path(settings.download_folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    if settings.use_archive and settings.archive_file:
        Path(settings.archive_file).expanduser().parent.mkdir(parents=True, exist_ok=True)
    _warn_disk_space(folder, log)

    def hook(data: dict[str, Any]) -> None:
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled by user.")
        progress(data)

    class SafeLogger:
        def debug(self, message: str) -> None:
            if message.startswith("[debug]"):
                log("DEBUG", _redact(message))

        def info(self, message: str) -> None:
            log("INFO", _redact(message))

        def warning(self, message: str) -> None:
            log("WARNING", _redact(message))

        def error(self, message: str) -> None:
            log("ERROR", _redact(message))

    yt_dlp = load_ytdlp()
    options = build_download_options(settings, hook, SafeLogger())
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            result = ydl.download([normalized])
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled by user.")
        if result:
            raise RuntimeError(f"yt-dlp exited with status {result}.")
    except DownloadCancelled:
        raise
    except Exception as exc:
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled by user.") from exc
        raise RuntimeError(_redact(str(exc))) from exc


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def archive_key_for_url(url: str) -> str | None:
    """Return yt-dlp's archive key when it can be derived without a request."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    host = parsed.netloc.lower().split(":", 1)[0]
    parts = [part for part in parsed.path.split("/") if part]
    if (
        host in {"redgifs.com", "www.redgifs.com"}
        and len(parts) >= 2
        and parts[0].lower() in {"watch", "ifr"}
    ):
        return f"redgifs {parts[1].lower()}"
    return None


def is_url_archived(url: str, settings: AppSettings) -> bool:
    if not settings.use_archive or not settings.archive_file.strip():
        return False
    key = archive_key_for_url(url)
    if not key:
        return False
    try:
        lines = Path(settings.archive_file).expanduser().read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    return key in {line.strip().lower() for line in lines if line.strip()}


def _warn_disk_space(folder: Path, log: LogCallback) -> None:
    try:
        free = shutil.disk_usage(folder).free
        if free < 1024**3:
            log("WARNING", f"Low disk space: {free / 1024**3:.1f} GiB free")
    except OSError:
        pass


def _redact(message: str) -> str:
    lowered = message.lower()
    if any(term in lowered for term in ("authorization:", "cookie:", "set-cookie:")):
        return "yt-dlp message redacted because it may contain authentication data."
    return message.replace("\r", " ").replace("\n", " ").strip()


def _parse_byte_rate(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGTP]?)B?(?:/S)?\s*", value, re.I)
    if not match:
        raise ValueError("Rate limit must be a number such as 500K or 2M.")
    units = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}
    return int(float(match.group(1)) * units[match.group(2).upper()])
