from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metadata import utc_now_iso
from .storage import load_json, save_json_atomic

STATE_SCHEMA_VERSION = "1.1"


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_hash(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fingerprint_file(path: str | Path, *, include_hash: bool = True) -> dict[str, Any]:
    """Return a file fingerprint. GUI status checks can omit the expensive hash."""
    path = Path(path)
    stat = path.stat()
    fingerprint = {
        "path": str(path.resolve()),
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
    }
    if include_hash:
        fingerprint["sha256"] = sha256_file(path)
    return fingerprint


@dataclass
class ProcessingState:
    """Crash-safe state for a Mode 0 processing job.

    The checkpoint is deliberately separate from final artifacts. It records the
    last *persisted* raw-landmark frame, so a restart can resume without risking
    partial final Parquet/MP4 files.
    """

    session_id: str
    video_id: str
    source_fingerprint: dict[str, Any]
    model_fingerprint: dict[str, Any]
    config_fingerprint: str
    status: str = "in_progress"
    stage: str = "inspect"
    next_frame: int = 0
    persisted_frames: int = 0
    checkpoint_chunks: list[str] = field(default_factory=list)
    error: str | None = None
    tracking_state: dict[str, Any] | None = None
    started_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    recording_identity: dict[str, str | None] | None = None

    @classmethod
    def new(
        cls,
        *,
        session_id: str,
        video_id: str,
        source_fingerprint: dict[str, Any],
        model_fingerprint: dict[str, Any],
        config_fingerprint: str,
        recording_identity: dict[str, str | None] | None = None,
    ) -> "ProcessingState":
        return cls(
            session_id=session_id,
            video_id=video_id,
            source_fingerprint=source_fingerprint,
            model_fingerprint=model_fingerprint,
            config_fingerprint=config_fingerprint,
            recording_identity=recording_identity,
        )

    @classmethod
    def load(cls, path: str | Path) -> "ProcessingState":
        document = load_json(path)
        if not isinstance(document, dict):
            raise ValueError("Processing state must be a JSON object.")
        if document.get("schema_version") not in {"1.0", STATE_SCHEMA_VERSION}:
            raise ValueError(
                f"Unsupported processing state schema: {document.get('schema_version')}"
            )
        return cls(
            session_id=str(document["session_id"]),
            video_id=str(document["video_id"]),
            source_fingerprint=dict(document["source_fingerprint"]),
            model_fingerprint=dict(document["model_fingerprint"]),
            config_fingerprint=str(document["config_fingerprint"]),
            status=str(document.get("status", "in_progress")),
            stage=str(document.get("stage", "inspect")),
            next_frame=int(document.get("next_frame", 0)),
            persisted_frames=int(document.get("persisted_frames", 0)),
            checkpoint_chunks=[str(item) for item in document.get("checkpoint_chunks", [])],
            error=document.get("error"),
            tracking_state=document.get("tracking_state"),
            started_at=str(document.get("started_at", utc_now_iso())),
            updated_at=str(document.get("updated_at", utc_now_iso())),
            recording_identity=(
                dict(document["recording_identity"])
                if document.get("recording_identity") is not None else None
            ),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "session_id": self.session_id,
            "video_id": self.video_id,
            "source_fingerprint": self.source_fingerprint,
            "model_fingerprint": self.model_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "status": self.status,
            "stage": self.stage,
            "next_frame": self.next_frame,
            "persisted_frames": self.persisted_frames,
            "checkpoint_chunks": self.checkpoint_chunks,
            "error": self.error,
            "tracking_state": self.tracking_state,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "recording_identity": self.recording_identity,
        }

    def save(self, path: str | Path) -> None:
        self.updated_at = utc_now_iso()
        save_json_atomic(self.to_document(), path)

    def compatible_quickly_with(
        self,
        *,
        source_fingerprint: dict[str, Any],
        model_fingerprint: dict[str, Any],
        config_fingerprint: str,
    ) -> bool:
        return (
            self.source_fingerprint.get("path") == source_fingerprint.get("path")
            and self.source_fingerprint.get("size_bytes") == source_fingerprint.get("size_bytes")
            and self.source_fingerprint.get("modified_ns") == source_fingerprint.get("modified_ns")
            and self.model_fingerprint.get("path") == model_fingerprint.get("path")
            and self.model_fingerprint.get("size_bytes") == model_fingerprint.get("size_bytes")
            and self.model_fingerprint.get("modified_ns") == model_fingerprint.get("modified_ns")
            and self.config_fingerprint == config_fingerprint
        )

    def compatible_with(
        self,
        *,
        source_fingerprint: dict[str, Any],
        model_fingerprint: dict[str, Any],
        config_fingerprint: str,
    ) -> bool:
        return (
            self.compatible_quickly_with(
                source_fingerprint=source_fingerprint,
                model_fingerprint=model_fingerprint,
                config_fingerprint=config_fingerprint,
            )
            and self.source_fingerprint.get("sha256") == source_fingerprint.get("sha256")
            and self.model_fingerprint.get("sha256") == model_fingerprint.get("sha256")
        )
