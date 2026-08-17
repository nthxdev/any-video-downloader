"""Application entry point."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.downloader import ffmpeg_available
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Any Video Downloader")
    app.setOrganizationName("Any Video Downloader")
    window = MainWindow()
    window.show()
    if not ffmpeg_available():
        QMessageBox.warning(
            window,
            "FFmpeg not found",
            "FFmpeg is required to merge video/audio and for post-processing. "
            "Install it before downloading.",
        )
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
