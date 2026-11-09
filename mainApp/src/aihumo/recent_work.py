"""Persistent recent-work registry for reopening AIHuMo sessions."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import load_json, save_json_atomic

SCHEMA_VERSION = "1.0"
MAX_RECENT = 10


class RecentWorkStore:
    """Keep the most recent workspaces first without storing feature data."""

    def __init__(self, path: str | Path, *, identity_keys=("featuresParquet", "processedVideo")):
        self.path = Path(path)
        self.identity_keys = identity_keys
        self.items: list[dict[str, Any]] = []
        self.dismissed: set[tuple] = set()
        self.load()

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            self.items = []
            self.dismissed.clear()
            return self.items
        document = load_json(self.path)
        self.dismissed = {
            self._identity(files) for files in document.get("dismissed", []) if isinstance(files, dict)
        }
        raw = document.get("items")
        if isinstance(raw, list):
            self.items = [dict(item) for item in raw if isinstance(item, dict)]
        else:
            # Read the dictionary-style form as well: mostRecent,
            # secondMostRecent, and so on.
            self.items = [dict(value) for _, value in sorted(document.get("recentWork", {}).items()) if isinstance(value, dict)]
        return self.items

    def _identity(self, files):
        return tuple(files.get(key) for key in self.identity_keys)

    def is_dismissed(self, files) -> bool:
        return self._identity(files) in self.dismissed

    def add(
        self, *, name: str, files: dict[str, str], identifiers: dict[str, Any] | None = None,
        last_frame: int | None = None,
    ) -> dict[str, Any]:
        entry = {
            "name": str(name),
            "files": {key: str(value) for key, value in files.items() if value},
            "identifiers": dict(identifiers or {}),
        }
        if last_frame is not None:
            entry["lastFrame"] = last_frame
        identity = self._identity(entry["files"])
        self.items = [
            item for item in self.items
            if self._identity(item.get("files", {})) != identity
        ]
        self.items.insert(0, entry)
        self.items = self.items[:MAX_RECENT]
        self.dismissed.discard(identity)
        self.save()
        return entry

    def remove(self, files, *, hide_discovered=False) -> None:
        """Forget a workspace in history without touching its files."""
        identity = self._identity(files)
        previous, dismissed = self.items, self.dismissed.copy()
        self.items = [item for item in self.items if self._identity(item.get("files", {})) != identity]
        if hide_discovered:
            self.dismissed.add(identity)
        try:
            self.save()
        except OSError:
            self.items, self.dismissed = previous, dismissed
            raise

    def save_frame(self, *, video: str, parquet: str, frame: int) -> bool:
        """Update a graph position without promoting an older workspace."""
        for entry in self.items:
            files = entry.get("files", {})
            if (files.get("processedVideo"), files.get("featuresParquet")) != (video, parquet):
                continue
            if entry.get("lastFrame") == frame:
                return False
            previous = entry.get("lastFrame")
            entry["lastFrame"] = frame
            try:
                self.save()
            except OSError:
                entry["lastFrame"] = previous
                raise
            return True
        return False

    def save(self) -> None:
        recent_work = {}
        names = ["mostRecent", "secondMostRecent", "thirdMostRecent"]
        for index, item in enumerate(self.items):
            key = names[index] if index < len(names) else f"recent_{index + 1}"
            recent_work[key] = item
        save_json_atomic({
            "schemaVersion": SCHEMA_VERSION,
            "items": self.items,
            "recentWork": recent_work,
            "dismissed": [dict(zip(self.identity_keys, identity)) for identity in sorted(self.dismissed)],
        }, self.path)
