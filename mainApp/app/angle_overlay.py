"""Read frame angles and draw their labels in the displayed video coordinates."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import pandas as pd
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap


# Vertices are MediaPipe landmark IDs. Midpoint angles use both landmarks.
ANGLE_VERTICES = {
    "angle_left_shoulder": (11,), "angle_right_shoulder": (12,),
    "angle_left_elbow": (13,), "angle_right_elbow": (14,),
    "angle_left_wrist": (15,), "angle_right_wrist": (16,),
    "angle_left_hip": (23,), "angle_right_hip": (24,),
    "angle_left_knee": (25,), "angle_right_knee": (26,),
    "angle_left_ankle": (27,), "angle_right_ankle": (28,),
    "angle_torso_nose_shoulder_hip": (11, 12),
    "angle_torso_vertical": (23, 24),
    "angle_shoulder_midpoint_hip_midpoint_knee_midpoint": (23, 24),
}


@dataclass(frozen=True)
class OverlayTrace:
    joint: str
    column: str
    color: str


@dataclass(frozen=True)
class AngleLabel:
    x: float
    y: float
    text: str
    color: str


def angle_name(joint: str) -> str:
    return {
        "angle_torso_nose_shoulder_hip": "Neck",
        "angle_shoulder_midpoint_hip_midpoint_knee_midpoint": "Hip Midpoint",
        "angle_torso_vertical": "Torso Tilt",
    }.get(joint, joint.removeprefix("angle_").replace("_", " ").title())


def frame_angle_labels(row: pd.Series, traces: tuple[OverlayTrace, ...]) -> tuple[AngleLabel, ...]:
    labels = []
    for trace in traces:
        landmarks = ANGLE_VERTICES.get(trace.joint)
        if not landmarks:
            continue
        try:
            value = float(row.get(trace.column))
            points = [(float(row[f"lm{index}_x"]), float(row[f"lm{index}_y"])) for index in landmarks]
        except (KeyError, TypeError, ValueError):
            continue
        x = sum(point[0] for point in points) / len(points)
        y = sum(point[1] for point in points) / len(points)
        if isfinite(value) and 0 <= x <= 1 and 0 <= y <= 1:
            labels.append(AngleLabel(x, y, f"{angle_name(trace.joint)} {value:.1f}°", trace.color))
    return tuple(labels)


def _place_label(anchor: QPoint, width: int, height: int, bounds: QRect, placed: list[QRect]) -> QRect:
    """Prefer the nearest clear space beside the vertex and keep labels in view."""
    gap = 8
    best = None
    best_overlap = float("inf")
    for step in range(6):
        offset = step * (height + 3)
        for top in (anchor.y() - height // 2 - offset, anchor.y() - height // 2 + offset):
            for left in (anchor.x() + gap, anchor.x() - width - gap):
                rect = QRect(
                    max(bounds.left(), min(left, bounds.right() - width + 1)),
                    max(bounds.top(), min(top, bounds.bottom() - height + 1)),
                    width, height,
                )
                overlaps = [rect.intersected(other.adjusted(-2, -2, 2, 2)) for other in placed]
                overlap = sum(hit.width() * hit.height() for hit in overlaps if not hit.isEmpty())
                if overlap == 0:
                    return rect
                if overlap < best_overlap:
                    best, best_overlap = rect, overlap
    return best


def paint_angle_labels(frame: QPixmap, labels: tuple[AngleLabel, ...]) -> None:
    if not labels or frame.width() < 48 or frame.height() < 32:
        return
    painter = QPainter(frame)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        bounds = frame.rect().adjusted(2, 2, -2, -2)
        placed = []
        for label in labels:
            anchor = QPoint(round(label.x * (frame.width() - 1)), round(label.y * (frame.height() - 1)))
            text = metrics.elidedText(label.text, Qt.TextElideMode.ElideRight, bounds.width() - 10)
            rect = _place_label(anchor, metrics.horizontalAdvance(text) + 10, metrics.height() + 6, bounds, placed)
            placed.append(rect)
            color = QColor(label.color)
            edge = QPoint(min(max(anchor.x(), rect.left()), rect.right()),
                          min(max(anchor.y(), rect.top()), rect.bottom()))
            painter.setPen(color)
            painter.drawLine(anchor, edge)
            painter.setBrush(color)
            painter.drawEllipse(anchor, 2, 2)
            painter.setBrush(QColor(16, 22, 30, 235))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    finally:
        painter.end()
