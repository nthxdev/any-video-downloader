"""JSON-backed application settings."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import DATA_DIR, AppSettings


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "settings.json"

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                return AppSettings()
            return AppSettings.from_dict(values)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
