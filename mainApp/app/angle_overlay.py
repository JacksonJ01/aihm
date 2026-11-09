"""Read frame angles and draw their labels in the displayed video coordinates."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import pandas as pd
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QPushButton


from aihumo.features import ANGLE_VERTICES
from aihumo.geometry import POSE_CONNECTIONS


MIDPOINTS = ("shoulder", "hip", "knee", "ankle")
MIDPOINT_PREFIXES = ("review_legacy_", "")
SKELETON_COLUMNS = {
    *(f"lm{i}_{axis}" for i in range(33) for axis in "xy"),
    *(f"{prefix}{point}_midpoint_{axis}" for prefix in MIDPOINT_PREFIXES for point in MIDPOINTS for axis in "xy"),
}


def midpoint_overlay_button(columns, *, baked: bool) -> QPushButton:
    available = any(all(f"{prefix}{point}_midpoint_{axis}" in columns for axis in "xy")
                    for prefix in MIDPOINT_PREFIXES for point in MIDPOINTS)
    button = QPushButton("Show Midpoint Overlay")
    button.setCheckable(True)
    button.setChecked(baked or available)
    button.setEnabled(available and not baked)
    if baked:
        button.setToolTip("The midpoint overlay is part of this video. A matching clean video is needed to hide it.")
    elif available:
        button.setToolTip("Draw the saved normalized-image midpoints and centerline.")
    else:
        button.setToolTip("No saved image midpoints. Use Prepare existing recording in the launcher.")
    return button


def paint_skeleton(pixmap: QPixmap, row: pd.Series, *, draw_body: bool, draw_centerline: bool) -> None:
    """Render saved normalized image positions onto the displayed video."""
    if pixmap.isNull() or not (draw_body or draw_centerline):
        return

    def point(prefix):
        try:
            x, y = float(row.get(f"{prefix}_x")), float(row.get(f"{prefix}_y"))
        except (TypeError, ValueError):
            return None
        if not (isfinite(x) and isfinite(y) and -2 <= x <= 3 and -2 <= y <= 3):
            return None
        return QPoint(round(x * (pixmap.width() - 1)), round(y * (pixmap.height() - 1)))

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if draw_body:
            points = [point(f"lm{i}") for i in range(33)]
            painter.setPen(QPen(QColor("#00cc44"), 2))
            for first, last in POSE_CONNECTIONS:
                if points[first] is not None and points[last] is not None:
                    painter.drawLine(points[first], points[last])
            painter.setPen(QPen(QColor("#ed3434"), 4))
            for landmark in points:
                if landmark is not None:
                    painter.drawPoint(landmark)
        if draw_centerline:
            chain = [point("lm0")]
            for name in MIDPOINTS:
                saved = next((f"{prefix}{name}_midpoint" for prefix in MIDPOINT_PREFIXES
                              if all(f"{prefix}{name}_midpoint_{axis}" in row for axis in "xy")), None)
                chain.append(point(saved) if saved is not None else None)
            painter.setPen(QPen(QColor("#00bfe8"), 2))
            for first, last in zip(chain, chain[1:]):
                if first is not None and last is not None:
                    painter.drawLine(first, last)
            for label, landmark in zip(("SM", "HM", "KM", "AM"), chain[1:]):
                if landmark is not None:
                    painter.drawEllipse(landmark, 3, 3)
                    painter.drawText(landmark + QPoint(5, -4), label)
    finally:
        painter.end()


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
