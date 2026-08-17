"""Metadata extraction using yt-dlp without downloading media."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import AppSettings
from app.services.downloader import is_url_archived
from app.services.link_parser import normalize_url
from app.services.ytdlp_loader import load_ytdlp


@dataclass(slots=True)
class MediaEntry:
    index: int
    title: str
    uploader: str
    duration: int | None
    url: str
    media_type: str = "Video"
    status: str = "Ready"


class ExtractionError(RuntimeError):
    pass


def _options(settings: AppSettings) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": max(1, settings.max_results),
        "socket_timeout": max(1, settings.socket_timeout),
        "ignoreerrors": True,
        "noplaylist": False,
    }
    if settings.browser:
        options["cookiesfrombrowser"] = (settings.browser,)
    return options


def analyze_url(
    url: str,
    settings: AppSettings,
    log: Callable[[str, str], None] | None = None,
) -> tuple[dict[str, Any], list[MediaEntry]]:
    normalized = normalize_url(url)
    if not normalized:
        raise ExtractionError("Enter a valid HTTP or HTTPS URL.")
    yt_dlp = load_ytdlp()
    if log:
        log("INFO", f"Analyzing {normalized}")
    try:
        with yt_dlp.YoutubeDL(_options(settings)) as ydl:
            info = ydl.extract_info(normalized, download=False)
            if info and _is_unpaged_redgifs_profile(normalized):
                info = _complete_redgifs_profile(ydl, normalized, info, settings.max_results, log)
    except Exception as exc:
        raise ExtractionError(_safe_error(exc)) from exc
    if not info:
        raise ExtractionError("yt-dlp did not return metadata for this URL.")

    raw_entries = info.get("entries")
    entries: list[MediaEntry] = []
    if raw_entries is not None:
        for index, item in enumerate(raw_entries, 1):
            if not item:
                continue
            entry_url = item.get("webpage_url") or item.get("url") or ""
            if entry_url and not entry_url.startswith(("http://", "https://")):
                extractor = item.get("ie_key") or item.get("extractor_key")
                entry_url = yt_dlp.YoutubeDL().sanitize_info(item).get("webpage_url") or entry_url
                if not entry_url.startswith(("http://", "https://")) and extractor:
                    entry_url = f"{extractor}:{entry_url}"
            entries.append(
                MediaEntry(
                    index=index,
                    title=str(item.get("title") or item.get("id") or "Untitled"),
                    uploader=str(item.get("uploader") or item.get("channel") or ""),
                    duration=_int_or_none(item.get("duration")),
                    url=str(entry_url),
                    media_type=_media_type(item),
                    status=("Archived" if is_url_archived(str(entry_url), settings) else "Ready"),
                )
            )
    else:
        entries.append(
            MediaEntry(
                index=1,
                title=str(info.get("title") or info.get("id") or "Untitled"),
                uploader=str(info.get("uploader") or info.get("channel") or ""),
                duration=_int_or_none(info.get("duration")),
                url=str(info.get("webpage_url") or normalized),
                media_type=_media_type(info),
                status=(
                    "Archived"
                    if is_url_archived(str(info.get("webpage_url") or normalized), settings)
                    else "Ready"
                ),
            )
        )
    if log:
        log("INFO", f"Discovered {len(entries)} item(s)")
    return info, entries


def available_formats(info: dict[str, Any], limit: int = 30) -> list[str]:
    result: list[str] = []
    for item in info.get("formats") or []:
        format_id = item.get("format_id", "?")
        resolution = item.get("resolution") or (
            f"{item.get('width', '?')}x{item.get('height', '?')}"
        )
        ext = item.get("ext", "?")
        note = item.get("format_note") or ""
        result.append(f"{format_id}: {ext} {resolution} {note}".strip())
        if len(result) >= limit:
            break
    return result


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_error(exc: Exception) -> str:
    message = str(exc).replace("\r", " ").replace("\n", " ").strip()
    for marker in ("Authorization:", "Cookie:", "cookies:"):
        if marker.lower() in message.lower():
            return "Extraction failed. Sensitive authentication details were redacted."
    return message or exc.__class__.__name__


def _is_unpaged_redgifs_profile(url: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    return (
        host in {"redgifs.com", "www.redgifs.com"}
        and parsed.path.lower().startswith("/users/")
        and "page" not in query
    )


def _profile_page_url(url: str, page: int) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _complete_redgifs_profile(
    ydl: Any,
    url: str,
    first_info: dict[str, Any],
    max_results: int,
    log: Callable[[str, str], None] | None,
) -> dict[str, Any]:
    """Work around short RedGIFs pages while still using its yt-dlp extractor."""
    combined: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(raw_entries: object) -> int:
        added = 0
        for entry in raw_entries or []:  # type: ignore[union-attr]
            if not entry:
                continue
            identity = str(entry.get("id") or entry.get("webpage_url") or entry.get("url"))
            if not identity or identity in seen:
                continue
            seen.add(identity)
            combined.append(entry)
            added += 1
            if len(combined) >= max_results:
                break
        return added

    add(first_info.get("entries"))
    # In RedGIFsUserIE, an explicit ?page=N currently requests API page N+1.
    # Continue until an empty page rather than assuming a short page is final.
    for page in range(1, max_results + 1):
        if len(combined) >= max_results:
            break
        if log:
            log("INFO", f"Loading RedGIFs profile page {page + 1}")
        page_info = ydl.extract_info(_profile_page_url(url, page), download=False)
        page_entries = page_info.get("entries") if page_info else None
        if not page_entries:
            break
        if add(page_entries) == 0:
            break
    result = dict(first_info)
    result["entries"] = combined
    return result


def _media_type(info: dict[str, Any]) -> str:
    ext = str(info.get("ext") or "").lower()
    if ext in {"jpg", "jpeg", "png", "webp", "avif", "gif"}:
        return "Image" if ext != "gif" else "GIF"
    if str(info.get("vcodec") or "").lower() == "none":
        return "Audio"
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
    return "GIF/Video" if "redgifs" in extractor else "Video"
