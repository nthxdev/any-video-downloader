"""Queue state records."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import Event


class QueueStatus(StrEnum):
    PENDING = "Pending"
    ANALYZING = "Analyzing"
    DOWNLOADING = "Downloading"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    SKIPPED = "Skipped"
    CANCELLED = "Cancelled"
    FAILED = "Failed"


@dataclass(slots=True)
class QueueItem:
    identifier: int
    title: str
    url: str
    status: QueueStatus = QueueStatus.PENDING
    progress: float = 0
    speed: str = ""
    eta: str = ""
    output_path: str = ""
    error: str = ""
    cancel_event: Event = field(default_factory=Event)
