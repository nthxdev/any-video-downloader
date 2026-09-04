"""Main application window."""

from __future__ import annotations

import html
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import PROJECT_ROOT, AppSettings
from app.models.queue import QueueItem, QueueStatus
from app.services.downloader import is_url_archived
from app.services.extractor import MediaEntry, available_formats
from app.services.link_parser import extract_links
from app.services.settings import SettingsStore
from app.workers.jobs import AnalysisJob, DownloadJob


def _button(text: str, callback: Any) -> QPushButton:
    result = QPushButton(text)
    result.clicked.connect(callback)
    return result


def _duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = SettingsStore()
        self.settings = self.store.load()
        self.analysis_pool = QThreadPool(self)
        self.analysis_pool.setMaxThreadCount(2)
        self.download_pool = QThreadPool(self)
        self.download_pool.setMaxThreadCount(self.settings.concurrent_downloads)
        self.network = QNetworkAccessManager(self)
        self.network.finished.connect(self._thumbnail_finished)
        self.bulk_urls: list[str] = []
        self.discovered: list[MediaEntry] = []
        self.queue_items: dict[int, QueueItem] = {}
        self.queue_rows: dict[int, int] = {}
        self.next_queue_id = 1
        self.active_analysis: AnalysisJob | None = None

        self.setWindowTitle("Any Video Downloader")
        self.resize(1200, 780)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._build_single()
        self._build_bulk()
        self._build_discovery()
        self._build_queue()
        self._build_logs()
        self._build_settings()
        self.statusBar().showMessage("Ready — download only content you may legally save.")
        self.log("INFO", "Application started")

    def _build_single(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        self.single_url = QLineEdit()
        self.single_url.setPlaceholderText("Paste a video, playlist, channel, or webpage URL")
        row.addWidget(self.single_url, 1)
        row.addWidget(_button("Analyze", lambda: self._analyze(self.single_url.text())))
        row.addWidget(_button("Download", self._download_single))
        row.addWidget(_button("Cancel", self._cancel_selected_queue))
        row.addWidget(_button("Open download folder", self._open_download_folder))
        layout.addLayout(row)

        content = QHBoxLayout()
        self.thumbnail = QLabel("Thumbnail")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setMinimumSize(320, 180)
        self.thumbnail.setMaximumSize(480, 270)
        self.thumbnail.setStyleSheet("border: 1px solid palette(mid);")
        content.addWidget(self.thumbnail)
        self.single_metadata = QPlainTextEdit()
        self.single_metadata.setReadOnly(True)
        self.single_metadata.setPlaceholderText("Metadata appears here after analysis.")
        content.addWidget(self.single_metadata, 1)
        layout.addLayout(content)
        self.formats = QPlainTextEdit()
        self.formats.setReadOnly(True)
        self.formats.setPlaceholderText("Available formats")
        layout.addWidget(self.formats, 1)
        layout.addWidget(
            QLabel(
                "Responsible use: download only content you own, have permission to "
                "download, or that is legally available."
            )
        )
        self.tabs.addTab(tab, "Single URL")

    def _build_bulk(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        buttons = QHBoxLayout()
        buttons.addWidget(_button("Load file", self._load_bulk))
        buttons.addWidget(_button("Select all", self._bulk_select_all))
        buttons.addWidget(_button("Select none", self._bulk_select_none))
        buttons.addWidget(_button("Remove selected", self._bulk_remove_selected))
        buttons.addWidget(_button("Clear", self._bulk_clear))
        buttons.addWidget(_button("Save cleaned list", self._bulk_save))
        buttons.addWidget(_button("Download selected", self._bulk_download))
        buttons.addStretch()
        layout.addLayout(buttons)
        self.bulk_table = QTableWidget(0, 2)
        self.bulk_table.setHorizontalHeaderLabels(["Download", "Normalized URL"])
        self.bulk_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.bulk_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.bulk_table)
        self.bulk_summary = QLabel("No links loaded.")
        layout.addWidget(self.bulk_summary)
        self.tabs.addTab(tab, "Bulk File")

    def _build_discovery(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        self.discovery_url = QLineEdit()
        self.discovery_url.setPlaceholderText(
            "Paste an exact profile, channel, playlist, collection, or webpage URL"
        )
        row.addWidget(self.discovery_url, 1)
        row.addWidget(_button("Analyze", lambda: self._analyze(self.discovery_url.text())))
        row.addWidget(_button("Select all", lambda: self._discovery_check(True)))
        row.addWidget(_button("Select none", lambda: self._discovery_check(False)))
        row.addWidget(_button("Invert", self._discovery_invert))
        row.addWidget(_button("Download selected", self._discovery_download_selected))
        row.addWidget(_button("Download all", self._discovery_download_all))
        row.addWidget(_button("Export URLs", self._discovery_export))
        layout.addLayout(row)
        self.discovery_table = QTableWidget(0, 8)
        self.discovery_table.setHorizontalHeaderLabels(
            ["Select", "#", "Type", "Title", "Uploader", "Duration", "URL", "Status"]
        )
        self.discovery_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.discovery_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch
        )
        self.discovery_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.discovery_table)
        self.discovery_summary = QLabel(
            f"Results are limited to {self.settings.max_results} items."
        )
        layout.addWidget(self.discovery_summary)
        self.tabs.addTab(tab, "Discovery")

    def _build_queue(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        row.addWidget(_button("Cancel selected", self._cancel_selected_queue))
        row.addWidget(_button("Retry failed", self._retry_failed))
        row.addWidget(_button("Clear completed", self._clear_completed))
        row.addWidget(_button("Open output folder", self._open_download_folder))
        row.addStretch()
        layout.addLayout(row)
        self.queue_table = QTableWidget(0, 8)
        self.queue_table.setHorizontalHeaderLabels(
            ["Title", "Source URL", "Progress", "Speed", "ETA", "Status", "Output", "Error"]
        )
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.queue_table)
        layout.addWidget(
            QLabel(
                "Pause/resume is intentionally unavailable: yt-dlp cannot pause every "
                "extractor reliably. Cancel and retry safely continues partial files."
            )
        )
        self.tabs.addTab(tab, "Download Queue")

    def _build_logs(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        row.addWidget(_button("Copy logs", self._copy_logs))
        row.addWidget(_button("Save logs", self._save_logs))
        row.addWidget(_button("Clear logs", lambda: self.logs.clear()))
        row.addStretch()
        layout.addLayout(row)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(5000)
        layout.addWidget(self.logs)
        self.tabs.addTab(tab, "Logs")

    def _build_settings(self) -> None:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        form = QFormLayout()
        self.download_folder = QLineEdit()
        self.download_folder.setText(self.settings.download_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.download_folder)
        folder_row.addWidget(_button("Browse", self._browse_download_folder))
        form.addRow("Download folder", folder_row)
        self.quality = QComboBox()
        self.quality.addItems(["Best quality", "Best up to 1080p", "Audio only"])
        self.quality.setCurrentIndex({"best": 0, "1080p": 1, "audio": 2}[self.settings.quality])
        form.addRow("Quality", self.quality)
        self.audio_format = QComboBox()
        self.audio_format.addItems(["mp3", "m4a", "opus", "flac", "wav"])
        self.audio_format.setCurrentText(self.settings.audio_format)
        form.addRow("Preferred audio format", self.audio_format)
        self.container = QComboBox()
        self.container.addItems(["auto", "mp4", "mkv", "webm"])
        self.container.setCurrentText(self.settings.container)
        form.addRow("Preferred container", self.container)
        self.subtitles = QCheckBox()
        self.subtitles.setChecked(self.settings.subtitles)
        form.addRow("Download subtitles", self.subtitles)
        self.write_thumbnail = QCheckBox()
        self.write_thumbnail.setChecked(self.settings.thumbnail)
        form.addRow("Write thumbnail", self.write_thumbnail)
        self.embed_metadata = QCheckBox()
        self.embed_metadata.setChecked(self.settings.embed_metadata)
        form.addRow("Embed metadata", self.embed_metadata)
        self.output_template = QLineEdit(self.settings.output_template)
        form.addRow("File naming template", self.output_template)
        self.concurrent = QSpinBox()
        self.concurrent.setRange(1, 8)
        self.concurrent.setValue(self.settings.concurrent_downloads)
        form.addRow("Concurrent downloads", self.concurrent)
        self.rate_limit = QLineEdit(self.settings.rate_limit)
        self.rate_limit.setPlaceholderText("Blank, or e.g. 2M")
        form.addRow("Rate limit", self.rate_limit)
        self.retries = QSpinBox()
        self.retries.setRange(0, 20)
        self.retries.setValue(self.settings.retries)
        form.addRow("Retry count", self.retries)
        self.browser = QComboBox()
        self.browser.addItem("None", "")
        for browser in (
            "brave",
            "chrome",
            "chromium",
            "edge",
            "firefox",
            "opera",
            "safari",
            "vivaldi",
            "whale",
        ):
            self.browser.addItem(browser.title(), browser)
        index = self.browser.findData(self.settings.browser)
        self.browser.setCurrentIndex(max(0, index))
        form.addRow("Cookies from browser", self.browser)
        self.archive_file = QLineEdit(self.settings.archive_file)
        form.addRow("Archive file", self.archive_file)
        self.use_archive = QCheckBox()
        self.use_archive.setChecked(self.settings.use_archive)
        form.addRow("Skip previously downloaded", self.use_archive)
        self.max_results = QSpinBox()
        self.max_results.setRange(1, 10000)
        self.max_results.setValue(self.settings.max_results)
        form.addRow("Maximum discovery results", self.max_results)
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 300)
        self.timeout.setValue(self.settings.socket_timeout)
        form.addRow("Network timeout (seconds)", self.timeout)
        outer.addLayout(form)
        outer.addWidget(
            QLabel(
                "Cookies are read directly by yt-dlp and are never stored by this app. "
                "Use only your own account and follow the website's rules."
            )
        )
        outer.addWidget(_button("Save settings", self._save_settings))
        outer.addStretch()
        self.tabs.addTab(tab, "Settings")

    def log(self, level: str, message: str) -> None:
        sanitized = html.escape(message.replace("\r", " ").replace("\n", " "))
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        self.logs.appendPlainText(f"{stamp} [{level}] {html.unescape(sanitized)}")

    def _analyze(self, url: str) -> None:
        if self.active_analysis:
            QMessageBox.information(self, "Analysis running", "Wait for analysis to finish.")
            return
        self._save_settings(show_message=False)
        job = AnalysisJob(url.strip(), self.settings)
        self.active_analysis = job
        job.signals.log.connect(self.log)
        job.signals.failed.connect(self._analysis_failed)
        job.signals.succeeded.connect(self._analysis_succeeded)
        job.signals.finished.connect(self._analysis_finished)
        self.statusBar().showMessage("Analyzing URL…")
        self.analysis_pool.start(job)

    def _analysis_finished(self) -> None:
        self.active_analysis = None
        self.statusBar().showMessage("Analysis finished", 5000)

    def _analysis_failed(self, error: str) -> None:
        self.log("ERROR", error)
        QMessageBox.warning(self, "Analysis failed", error)

    def _analysis_succeeded(self, info: dict[str, Any], entries: list[MediaEntry]) -> None:
        self.discovered = entries
        metadata = [
            f"Title: {info.get('title') or info.get('id') or ''}",
            f"Uploader: {info.get('uploader') or info.get('channel') or ''}",
            f"Duration: {_duration(info.get('duration'))}",
            f"Website/extractor: {info.get('extractor_key') or info.get('extractor') or ''}",
            f"Discovered items: {len(entries)}",
            f"Webpage: {info.get('webpage_url') or ''}",
        ]
        self.single_metadata.setPlainText("\n".join(metadata))
        formats = available_formats(info)
        self.formats.setPlainText("\n".join(formats) or "Formats are resolved at download time.")
        self._populate_discovery()
        thumbnail_url = info.get("thumbnail")
        if thumbnail_url:
            request = QNetworkRequest(QUrl(str(thumbnail_url)))
            request.setRawHeader(b"User-Agent", b"Any Video Downloader/0.1")
            self.network.get(request)
            self.thumbnail.setText("Loading thumbnail…")
        else:
            self.thumbnail.setText("No thumbnail available")

    def _thumbnail_finished(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.thumbnail.setText("Thumbnail unavailable")
                return
            data = reply.readAll()
            if len(data) > 8 * 1024 * 1024:
                self.thumbnail.setText("Thumbnail too large")
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self.thumbnail.setPixmap(
                    pixmap.scaled(
                        self.thumbnail.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self.thumbnail.setText("Thumbnail unavailable")
        finally:
            reply.deleteLater()

    def _download_single(self) -> None:
        url = self.single_url.text().strip()
        title = "Single download"
        text = self.single_metadata.toPlainText()
        if text.startswith("Title: "):
            title = text.splitlines()[0][7:] or title
        self._enqueue(title, url)

    def _load_bulk(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Load links", str(PROJECT_ROOT), "Link files (*.txt *.md *.csv)"
        )
        if name:
            self._load_bulk_path(Path(name))

    def _load_bulk_path(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, "Could not load file", str(exc))
            return
        self.bulk_urls, duplicates = extract_links(text)
        self._populate_bulk()
        self.bulk_summary.setText(
            f"{len(self.bulk_urls)} unique link(s) loaded from {path.name}; "
            f"{duplicates} duplicate(s) removed."
        )
        self.log("INFO", self.bulk_summary.text())

    def _populate_bulk(self) -> None:
        self.bulk_table.setRowCount(len(self.bulk_urls))
        for row, url in enumerate(self.bulk_urls):
            check = QCheckBox()
            check.setChecked(True)
            self.bulk_table.setCellWidget(row, 0, check)
            item = QTableWidgetItem(url)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.bulk_table.setItem(row, 1, item)

    def _bulk_select_all(self) -> None:
        for row in range(self.bulk_table.rowCount()):
            widget = self.bulk_table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(True)

    def _bulk_select_none(self) -> None:
        for row in range(self.bulk_table.rowCount()):
            widget = self.bulk_table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)

    def _bulk_remove_selected(self) -> None:
        rows = {item.row() for item in self.bulk_table.selectedItems()}
        self.bulk_urls = [url for index, url in enumerate(self.bulk_urls) if index not in rows]
        self._populate_bulk()
        self.bulk_summary.setText(f"{len(self.bulk_urls)} unique link(s).")

    def _bulk_clear(self) -> None:
        self.bulk_urls.clear()
        self._populate_bulk()
        self.bulk_summary.setText("No links loaded.")

    def _bulk_save(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "Save cleaned links", str(PROJECT_ROOT / "links.txt"), "Text (*.txt)"
        )
        if not name:
            return
        try:
            Path(name).write_text("".join(f"{url}\n" for url in self.bulk_urls), encoding="utf-8")
            self.log("INFO", f"Saved {len(self.bulk_urls)} links to {name}")
        except OSError as exc:
            QMessageBox.warning(self, "Could not save file", str(exc))

    def _bulk_download(self) -> None:
        count = 0
        for row, url in enumerate(self.bulk_urls):
            widget = self.bulk_table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox) and widget.isChecked():
                self._enqueue(Path(QUrl(url).path()).name or "Bulk download", url)
                count += 1
        self._show_queue(count)

    def _populate_discovery(self) -> None:
        self.discovery_table.setRowCount(len(self.discovered))
        for row, entry in enumerate(self.discovered):
            check = QCheckBox()
            check.setChecked(entry.status != "Archived")
            self.discovery_table.setCellWidget(row, 0, check)
            values = [
                str(entry.index),
                entry.media_type,
                entry.title,
                entry.uploader,
                _duration(entry.duration),
                entry.url,
                entry.status,
            ]
            for column, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.discovery_table.setItem(row, column, item)
        self.discovery_summary.setText(
            f"{len(self.discovered)} item(s) discovered; "
            f"{sum(entry.status == 'Archived' for entry in self.discovered)} already archived; "
            f"maximum {self.settings.max_results}."
        )

    def _discovery_check(self, checked: bool) -> None:
        for row in range(self.discovery_table.rowCount()):
            widget = self.discovery_table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(checked)

    def _discovery_invert(self) -> None:
        for row in range(self.discovery_table.rowCount()):
            widget = self.discovery_table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(not widget.isChecked())

    def _selected_discovery(self, all_items: bool = False) -> list[MediaEntry]:
        result = []
        for row, entry in enumerate(self.discovered):
            widget = self.discovery_table.cellWidget(row, 0)
            if all_items or (isinstance(widget, QCheckBox) and widget.isChecked()):
                result.append(entry)
        return result

    def _discovery_download_selected(self) -> None:
        self._enqueue_entries(self._selected_discovery())

    def _discovery_download_all(self) -> None:
        self._enqueue_entries(self._selected_discovery(all_items=True))

    def _enqueue_entries(self, entries: list[MediaEntry]) -> None:
        count = 0
        for entry in entries:
            if entry.url.startswith(("http://", "https://")):
                self._enqueue(entry.title, entry.url)
                count += 1
            else:
                self.log("WARNING", f"Skipped unresolved entry URL: {entry.title}")
        self._show_queue(count)

    def _discovery_export(self) -> None:
        entries = self._selected_discovery()
        name, _ = QFileDialog.getSaveFileName(
            self,
            "Export discovered URLs",
            str(PROJECT_ROOT / "discovered.txt"),
            "Text (*.txt)",
        )
        if not name:
            return
        urls = [entry.url for entry in entries if entry.url.startswith(("http://", "https://"))]
        try:
            Path(name).write_text("".join(f"{url}\n" for url in urls), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Could not export URLs", str(exc))

    def _enqueue(self, title: str, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "Invalid URL", "Enter a valid HTTP or HTTPS URL.")
            return
        self._save_settings(show_message=False)
        identifier = self.next_queue_id
        self.next_queue_id += 1
        item = QueueItem(identifier=identifier, title=title, url=url)
        self.queue_items[identifier] = item
        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)
        self.queue_rows[identifier] = row
        self.queue_table.setItem(row, 0, QTableWidgetItem(title))
        self.queue_table.setItem(row, 1, QTableWidgetItem(url))
        progress = QProgressBar()
        progress.setRange(0, 100)
        self.queue_table.setCellWidget(row, 2, progress)
        for column, value in enumerate(("", "", item.status.value, "", ""), 3):
            self.queue_table.setItem(row, column, QTableWidgetItem(value))
        if is_url_archived(url, self.settings):
            item.status = QueueStatus.SKIPPED
            item.progress = 100
            progress.setValue(100)
            self.queue_table.item(row, 5).setText(item.status.value)
            self.queue_table.item(row, 7).setText("Already present in download archive")
            self.log("INFO", f"Skipped archived item: {title}")
            return
        job = DownloadJob(item, AppSettings.from_dict(self.settings.to_dict()))
        job.signals.log.connect(self.log)
        job.signals.status.connect(self._queue_status)
        job.signals.progress.connect(self._queue_progress)
        job.signals.failed.connect(self._queue_failed)
        job.signals.finished.connect(self._queue_finished)
        self.download_pool.start(job)

    def _queue_status(self, identifier: int, status: str) -> None:
        item = self.queue_items.get(identifier)
        if not item:
            return
        item.status = QueueStatus(status)
        row = self.queue_rows[identifier]
        self.queue_table.item(row, 5).setText(status)

    def _queue_progress(self, identifier: int, data: dict[str, Any]) -> None:
        item = self.queue_items.get(identifier)
        if not item:
            return
        row = self.queue_rows[identifier]
        status = data.get("status")
        if status == "finished" or data.get("postprocessor"):
            self._queue_status(identifier, "Processing")
            item.progress = 100
        else:
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            item.progress = min(100, downloaded * 100 / total) if total else 0
        progress = self.queue_table.cellWidget(row, 2)
        if isinstance(progress, QProgressBar):
            progress.setValue(round(item.progress))
        speed = data.get("_speed_str") or ""
        eta = data.get("_eta_str") or ""
        filename = data.get("filename") or data.get("info_dict", {}).get("_filename") or ""
        item.speed, item.eta, item.output_path = str(speed), str(eta), str(filename)
        self.queue_table.item(row, 3).setText(item.speed)
        self.queue_table.item(row, 4).setText(item.eta)
        self.queue_table.item(row, 6).setText(item.output_path)

    def _queue_failed(self, identifier: int, error: str) -> None:
        item = self.queue_items.get(identifier)
        if not item:
            return
        item.status = QueueStatus.FAILED
        item.error = error
        row = self.queue_rows[identifier]
        self.queue_table.item(row, 5).setText(item.status.value)
        self.queue_table.item(row, 7).setText(error)
        self.log("ERROR", f"{item.title}: {error}")

    def _queue_finished(self, identifier: int) -> None:
        item = self.queue_items.get(identifier)
        if item and item.status == QueueStatus.COMPLETED:
            row = self.queue_rows[identifier]
            progress = self.queue_table.cellWidget(row, 2)
            if isinstance(progress, QProgressBar):
                progress.setValue(100)

    def _selected_queue_ids(self) -> list[int]:
        selected_rows = {index.row() for index in self.queue_table.selectionModel().selectedRows()}
        return [identifier for identifier, row in self.queue_rows.items() if row in selected_rows]

    def _cancel_selected_queue(self) -> None:
        for identifier in self._selected_queue_ids():
            item = self.queue_items[identifier]
            if item.status in {
                QueueStatus.PENDING,
                QueueStatus.ANALYZING,
                QueueStatus.DOWNLOADING,
                QueueStatus.PROCESSING,
            }:
                item.cancel_event.set()
                self.log("INFO", f"Cancellation requested: {item.title}")

    def _retry_failed(self) -> None:
        failed = [
            item
            for item in self.queue_items.values()
            if item.status in {QueueStatus.FAILED, QueueStatus.CANCELLED}
        ]
        for item in failed:
            self._enqueue(item.title, item.url)
        self._show_queue(len(failed))

    def _clear_completed(self) -> None:
        remove_ids = [
            identifier
            for identifier, item in self.queue_items.items()
            if item.status
            in {
                QueueStatus.COMPLETED,
                QueueStatus.SKIPPED,
                QueueStatus.CANCELLED,
            }
        ]
        for identifier in sorted(remove_ids, key=self.queue_rows.get, reverse=True):
            row = self.queue_rows.pop(identifier)
            self.queue_table.removeRow(row)
            self.queue_items.pop(identifier)
        for row, identifier in enumerate(
            key for key, _ in sorted(self.queue_rows.items(), key=lambda pair: pair[1])
        ):
            self.queue_rows[identifier] = row

    def _show_queue(self, count: int) -> None:
        if count:
            self.tabs.setCurrentWidget(self.queue_table.parentWidget())
            self.statusBar().showMessage(f"Queued {count} download(s)", 5000)

    def _open_download_folder(self) -> None:
        path = Path(self.settings.download_folder).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _browse_download_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose download folder", self.download_folder.text()
        )
        if path:
            self.download_folder.setText(path)

    def _settings_from_form(self) -> AppSettings:
        return AppSettings(
            download_folder=self.download_folder.text().strip(),
            quality=("best", "1080p", "audio")[self.quality.currentIndex()],
            audio_format=self.audio_format.currentText(),
            container=self.container.currentText(),
            subtitles=self.subtitles.isChecked(),
            thumbnail=self.write_thumbnail.isChecked(),
            embed_metadata=self.embed_metadata.isChecked(),
            output_template=self.output_template.text().strip(),
            concurrent_downloads=self.concurrent.value(),
            rate_limit=self.rate_limit.text().strip(),
            retries=self.retries.value(),
            browser=str(self.browser.currentData() or ""),
            archive_file=self.archive_file.text().strip(),
            use_archive=self.use_archive.isChecked(),
            max_results=self.max_results.value(),
            socket_timeout=self.timeout.value(),
        )

    def _save_settings(self, _checked: bool = False, show_message: bool = True) -> None:
        candidate = self._settings_from_form()
        if not candidate.download_folder or not candidate.output_template:
            if show_message:
                QMessageBox.warning(
                    self, "Invalid settings", "Download folder and template are required."
                )
            return
        try:
            self.store.save(candidate)
        except OSError as exc:
            if show_message:
                QMessageBox.warning(self, "Could not save settings", str(exc))
            return
        self.settings = candidate
        self.download_pool.setMaxThreadCount(candidate.concurrent_downloads)
        self.discovery_summary.setText(f"Results are limited to {candidate.max_results} items.")
        if show_message:
            self.statusBar().showMessage("Settings saved", 5000)
        self.log("INFO", "Settings saved")

    def _copy_logs(self) -> None:
        QApplication.clipboard().setText(self.logs.toPlainText())

    def _save_logs(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "Save logs", str(PROJECT_ROOT / "data" / "application.log"), "Log (*.log)"
        )
        if not name:
            return
        try:
            Path(name).parent.mkdir(parents=True, exist_ok=True)
            Path(name).write_text(self.logs.toPlainText() + "\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Could not save logs", str(exc))

    def closeEvent(self, event: Any) -> None:
        active = [
            item
            for item in self.queue_items.values()
            if item.status in {QueueStatus.PENDING, QueueStatus.DOWNLOADING, QueueStatus.PROCESSING}
        ]
        if active:
            answer = QMessageBox.question(
                self,
                "Downloads are active",
                "Cancel active downloads and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for item in active:
                item.cancel_event.set()
            self.download_pool.waitForDone(5000)
        self._save_settings(show_message=False)
        event.accept()


def system_summary() -> str:
    ffmpeg = shutil.which("ffmpeg") or "not found"
    return f"FFmpeg: {ffmpeg}"
