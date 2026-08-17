"""QRunnable jobs that communicate exclusively through Qt signals."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from app.config import AppSettings
from app.models.queue import QueueItem
from app.services.downloader import DownloadCancelled, download_url
from app.services.extractor import analyze_url


class AnalysisSignals(QObject):
    succeeded = Signal(object, object)
    failed = Signal(str)
    log = Signal(str, str)
    finished = Signal()


class AnalysisJob(QRunnable):
    def __init__(self, url: str, settings: AppSettings) -> None:
        super().__init__()
        self.url = url
        self.settings = settings
        self.signals = AnalysisSignals()

    @Slot()
    def run(self) -> None:
        try:
            info, entries = analyze_url(self.url, self.settings, self.signals.log.emit)
            self.signals.succeeded.emit(info, entries)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class DownloadSignals(QObject):
    progress = Signal(int, object)
    status = Signal(int, str)
    log = Signal(str, str)
    failed = Signal(int, str)
    finished = Signal(int)


class DownloadJob(QRunnable):
    def __init__(self, item: QueueItem, settings: AppSettings) -> None:
        super().__init__()
        self.item = item
        self.settings = settings
        self.signals = DownloadSignals()

    @Slot()
    def run(self) -> None:
        self.signals.status.emit(self.item.identifier, "Downloading")
        try:
            download_url(
                self.item.url,
                self.settings,
                self.item.cancel_event,
                lambda data: self.signals.progress.emit(self.item.identifier, data),
                self.signals.log.emit,
            )
            self.signals.status.emit(self.item.identifier, "Completed")
        except DownloadCancelled:
            self.signals.status.emit(self.item.identifier, "Cancelled")
        except Exception as exc:
            self.signals.failed.emit(self.item.identifier, str(exc))
        finally:
            self.signals.finished.emit(self.item.identifier)
