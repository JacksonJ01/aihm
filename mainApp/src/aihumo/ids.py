from __future__ import annotations
import uuid

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"

def make_session_id() -> str:
    return new_id("S")

def make_video_id() -> str:
    return new_id("V")
