"""Small, versioned workspace snapshots used by the desktop launcher.

The snapshot deliberately stores references and UI state only.  Videos,
Parquet files, and annotations remain separate artifacts owned by their
existing pipelines.  This makes resume state useful without duplicating or
mutating scientific data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .storage import load_json, save_json_atomic

SCHEMA_VERSION = "1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class WorkspaceSnapshot:
    workspace_id: str = field(default_factory=lambda: uuid4().hex)
    mode: int = 1
    files: dict[str, str] = field(default_factory=dict)
    identifiers: dict[str, Any] = field(default_factory=dict)
    current_frame: int = 0
    graph_source: str = ""
    selected_joints: list[str] = field(default_factory=list)
    layer_filter: list[str] = field(default_factory=list)
    layout: dict[str, Any] = field(default_factory=dict)
    unsaved_changes: bool = False
    updated_at: str = field(default_factory=_now)

    def to_document(self) -> dict[str, Any]:
        document = asdict(self)
        document["schemaVersion"] = SCHEMA_VERSION
        return document

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "WorkspaceSnapshot":
        if not isinstance(document, dict):
            raise ValueError("Workspace snapshot must be an object.")
        mode = document.get("mode", 1)
        if type(mode) is not int or mode < 0 or mode > 5:
            raise ValueError("Workspace mode must be an integer from 0 through 5.")
        frame = document.get("current_frame", document.get("lastFrame", 0))
        if type(frame) is not int or frame < 0:
            raise ValueError("Workspace frame must be a non-negative integer.")
        files = document.get("files", {})
        identifiers = document.get("identifiers", {})
        if not isinstance(files, dict) or not isinstance(identifiers, dict):
            raise ValueError("Workspace files and identifiers must be objects.")
        return cls(
            workspace_id=str(document.get("workspace_id", document.get("workspaceId", uuid4().hex))),
            mode=mode,
            files={str(key): str(value) for key, value in files.items() if value},
            identifiers=dict(identifiers),
            current_frame=frame,
            graph_source=str(document.get("graph_source", document.get("graphSource", "")) or ""),
            selected_joints=[str(value) for value in document.get("selected_joints", []) if value],
            layer_filter=[str(value) for value in document.get("layer_filter", []) if value],
            layout=dict(document.get("layout", {})) if isinstance(document.get("layout", {}), dict) else {},
            unsaved_changes=document.get("unsaved_changes", False) is True,
            updated_at=str(document.get("updated_at", document.get("updatedAt", _now()))),
        )


class WorkspaceStore:
    """Persist a bounded collection of workspace snapshots atomically."""

    def __init__(self, path: str | Path, *, limit: int = 20):
        self.path = Path(path)
        self.limit = max(1, int(limit))
        self.items: list[WorkspaceSnapshot] = []
        self.load()

    def load(self) -> list[WorkspaceSnapshot]:
        if not self.path.is_file():
            self.items = []
            return self.items
        document = load_json(self.path)
        raw = document.get("items", []) if isinstance(document, dict) else []
        self.items = []
        for item in raw:
            try:
                self.items.append(WorkspaceSnapshot.from_document(item))
            except (TypeError, ValueError):
                continue
        return self.items

    def save(self) -> None:
        save_json_atomic({
            "schemaVersion": SCHEMA_VERSION,
            "items": [item.to_document() for item in self.items[:self.limit]],
        }, self.path)

    def upsert(self, snapshot: WorkspaceSnapshot) -> WorkspaceSnapshot:
        snapshot.updated_at = _now()
        self.items = [item for item in self.items if item.workspace_id != snapshot.workspace_id]
        self.items.insert(0, snapshot)
        self.items = self.items[:self.limit]
        self.save()
        return snapshot

    def update_frame(self, workspace_id: str, frame: int) -> bool:
        if type(frame) is not int or frame < 0:
            raise ValueError("Workspace frame must be a non-negative integer.")
        for item in self.items:
            if item.workspace_id == workspace_id:
                if item.current_frame == frame:
                    return False
                previous = item.current_frame
                item.current_frame = frame
                try:
                    self.save()
                except OSError:
                    item.current_frame = previous
                    raise
                return True
        return False

    def remove(self, workspace_id: str) -> bool:
        previous = len(self.items)
        self.items = [item for item in self.items if item.workspace_id != workspace_id]
        if len(self.items) == previous:
            return False
        self.save()
        return True
