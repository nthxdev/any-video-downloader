"""Load yt-dlp from the vendored checkout, with installed-package fallback."""

from __future__ import annotations

import sys

from app.config import VENDOR_YTDLP


def load_ytdlp():
    if VENDOR_YTDLP.is_dir() and str(VENDOR_YTDLP) not in sys.path:
        sys.path.insert(0, str(VENDOR_YTDLP))
    import yt_dlp  # type: ignore[import-not-found]

    return yt_dlp
