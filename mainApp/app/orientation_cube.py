"""Clickable and draggable orientation control for the saved world pose."""
from __future__ import annotations

from math import atan2, cos, degrees, hypot, radians, sin

import numpy as np
from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPalette, QPen, QPolygonF
from PyQt6.QtWidgets import QGridLayout, QToolButton, QWidget


# Matplotlib displays the saved MediaPipe coordinates as X, Z, −Y.
_FACE_LABELS = (("−X", "+X"), ("−Z", "+Z"), ("+Y", "−Y"))
_BOUNDARIES = (-1, -0.62, 0.62, 1)


class OrientationCube(QWidget):
    view_changed = pyqtSignal(float, float, float)

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(122, 146)
        self.setMouseTracking(True)
        self.setAccessibleName("3D pose orientation")
        self.setToolTip("Drag to orbit. Click a face, edge, or corner to snap to it.")
        self._view = None
        self._press = None
        self._dragging = False
        self._hover = None
        self._faces = []
        self._regions = []

        buttons = QGridLayout(self)
        buttons.setContentsMargins(4, 98, 4, 4)
        buttons.setSpacing(2)
        for column, axis in enumerate((0, 2, 1)):
            for row, sign in enumerate((1, -1) if axis != 2 else (-1, 1)):
                button = QToolButton()
                label = _FACE_LABELS[axis][sign > 0]
                direction = tuple(sign if component == axis else 0 for component in range(3))
                button.setText(label)
                button.setFixedSize(36, 21)
                button.setAccessibleName(f"View along {label}")
                button.clicked.connect(lambda _checked, direction=direction: self.snap(direction))
                buttons.addWidget(button, row, column)

    def set_view(self, elev, azim, roll):
        view = elev, azim, roll
        if view == self._view:
            return
        self._view = view
        e, a, r = map(radians, view)
        forward = np.array((cos(e) * cos(a), cos(e) * sin(a), sin(e)))
        right = np.array((-sin(a), cos(a), 0))
        up = np.cross(forward, right)
        if cos(e) < 0:
            right, up = -right, -up
        projection = np.array((cos(r) * right - sin(r) * up, -sin(r) * right - cos(r) * up))

        self._faces.clear()
        self._regions.clear()
        self._hover = None
        for axis, depth in enumerate(forward):
            if abs(depth) < 1e-6:
                continue
            sign = 1 if depth > 0 else -1
            u, v = [component for component in range(3) if component != axis]
            grid = np.full((4, 4, 3), sign, dtype=float)
            grid[:, :, u] = _BOUNDARIES
            grid[:, :, v] = np.asarray(_BOUNDARIES)[:, None]
            projected = grid @ projection.T * 26 + (self.width() / 2, 50)
            face = QPolygonF([QPointF(*projected[i, j]) for i, j in ((0, 0), (0, 3), (3, 3), (3, 0))])
            self._faces.append((face, _FACE_LABELS[axis][sign > 0], abs(depth)))
            for row in range(3):
                for column in range(3):
                    corners = ((row, column), (row, column + 1), (row + 1, column + 1), (row + 1, column))
                    polygon = QPolygonF([QPointF(*projected[i, j]) for i, j in corners])
                    direction = [0, 0, 0]
                    direction[axis], direction[u], direction[v] = sign, column - 1, row - 1
                    self._regions.append((polygon, tuple(direction)))
        self.update()

    def snap(self, direction):
        x, y, z = direction
        horizontal = hypot(x, y)
        elev = degrees(atan2(z, horizontal))
        azim = degrees(atan2(y, x)) if horizontal else -90.0
        self.view_changed.emit(elev, azim, 0.0)

    def _region_at(self, position):
        return next((region for region in self._regions if region[0].containsPoint(position, Qt.FillRule.WindingFill)), None)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = self.palette().color(QPalette.ColorRole.Base)
        background.setAlpha(235)
        painter.setBrush(background)
        painter.setPen(self.palette().color(QPalette.ColorRole.Mid))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)
        for face, label, depth in self._faces:
            painter.setPen(QPen(QColor("#56718f"), 1))
            painter.setBrush(QColor(185 + round(depth * 38), 203 + round(depth * 26), 221 + round(depth * 18)))
            painter.drawPolygon(face)
            if self._hover is not None and face.containsPoint(self._hover[0].boundingRect().center(), Qt.FillRule.WindingFill):
                painter.setBrush(QColor(35, 126, 222, 105))
                painter.drawPolygon(self._hover[0])
            if depth > 0.22:
                center = face.boundingRect().center()
                painter.setPen(QColor("#162d47"))
                painter.drawText(QPointF(center.x() - painter.fontMetrics().horizontalAdvance(label) / 2,
                                         center.y() + painter.fontMetrics().ascent() / 3), label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._view is not None:
            self._press = event.position(), self._view
            self._dragging = False
            event.accept()

    def mouseMoveEvent(self, event):
        if self._press is not None:
            start, (elev, azim, roll) = self._press
            delta = event.position() - start
            if self._dragging or delta.manhattanLength() >= 4:
                if not self._dragging:
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._dragging = True
                self.view_changed.emit(max(-90, min(90, elev + delta.y())), azim - delta.x(), roll)
                return
        self._hover = self._region_at(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._hover else Qt.CursorShape.OpenHandCursor)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            self._press = None
            if not self._dragging and (region := self._region_at(event.position())) is not None:
                self.snap(region[1])
            self.unsetCursor()
            event.accept()

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)
