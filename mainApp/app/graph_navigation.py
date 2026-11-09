"""Zoom controls shared by the video-linked plots."""
from __future__ import annotations

from matplotlib.backend_bases import MouseButton
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from PyQt6.QtWidgets import QPushButton


def centered_time_limits(bounds, center, width):
    low, high = bounds
    width = min(high - low, max(1e-9, float(width)))
    start = min(high - width, max(low, float(center) - width / 2))
    return start, min(high, start + width)


def wheel_zoom_factor(event):
    steps = getattr(event, "step", 1 if event.button == "up" else -1)
    native = getattr(event, "guiEvent", None)
    if native is not None and native.pixelDelta().y():
        steps = native.pixelDelta().y() / 60.0
    return 0.65 ** max(-3, min(3, steps))


def zoom_to_seek_button(parent):
    button = QPushButton("Zoom to Seek", parent)
    button.setCheckable(True)
    button.setMinimumWidth(button.fontMetrics().horizontalAdvance("Zoom at Playhead") + 24)
    button.setStyleSheet(
        "QPushButton:checked { background-color: palette(highlight); color: palette(highlighted-text); "
        "border: 1px solid palette(highlight); border-radius: 4px; }"
    )
    button.toggled.connect(lambda seeking: button.setText("Zoom at Playhead" if seeking else "Zoom to Seek"))
    button.setToolTip(
        "Off: zoom around the green playhead. On: zoom over the graph to seek to that time."
    )
    return button


class FrameZoomToolbar(NavigationToolbar2QT):
    """Use the drag size for zoom and let the viewer pick the center."""

    def __init__(self, canvas, parent, scale_view, *, spatial=False, seek_on_zoom=None):
        self._scale_view = scale_view
        self._spatial = spatial
        self._seek_on_zoom = seek_on_zoom
        self._zoom_drag = None
        super().__init__(canvas, parent)
        if spatial:
            canvas.mpl_connect("button_press_event", self._press_spatial_zoom)
            canvas.mpl_connect("button_release_event", self._release_spatial_zoom)

    def _press_spatial_zoom(self, event):
        if not self.mode and event.button == MouseButton.RIGHT:
            self._start_drag(event, rectangle=False)

    def _release_spatial_zoom(self, event):
        if not self.mode and event.button == MouseButton.RIGHT:
            self._apply_drag(event)

    def zoom(self, *args):
        self._finish_drag()
        super().zoom(*args)

    def pan(self, *args):
        self._finish_drag()
        super().pan(*args)

    def press_zoom(self, event):
        self._start_drag(event, rectangle=True)

    def release_zoom(self, event):
        self._apply_drag(event)

    def press_pan(self, event):
        if event.button == MouseButton.RIGHT:
            self._start_drag(event, rectangle=False)
        else:
            self._finish_drag()
            super().press_pan(event)

    def release_pan(self, event):
        if self._zoom_drag is not None:
            self._apply_drag(event)
        else:
            super().release_pan(event)

    def _start_drag(self, event, *, rectangle):
        axis = event.inaxes
        if (axis is None or not axis.get_navigate()
                or not (axis.can_zoom() or (self._spatial and axis.name == "3d"))
                or event.button not in (MouseButton.LEFT, MouseButton.RIGHT) or event.x is None):
            return
        self._finish_drag()
        connection = self.canvas.mpl_connect("motion_notify_event", self._draw_zoom_drag) if rectangle else None
        self._zoom_drag = axis, event.x, event.button, rectangle, connection

    def _draw_zoom_drag(self, event):
        if self._zoom_drag is None:
            return
        axis, start, button, _, _ = self._zoom_drag
        buttons = getattr(event, "buttons", None)
        if buttons is not None and button not in buttons:
            self._finish_drag()
        elif event.x is not None:
            end = min(axis.bbox.xmax, max(axis.bbox.xmin, event.x))
            self.draw_rubberband(event, start, axis.bbox.ymin, end, axis.bbox.ymax)

    def _finish_drag(self):
        drag, self._zoom_drag = self._zoom_drag, None
        if drag is not None and drag[-1] is not None:
            self.canvas.mpl_disconnect(drag[-1])
            self.remove_rubberband()
        return drag

    def _apply_drag(self, event):
        drag = self._finish_drag()
        if drag is None or event is None or event.x is None:
            return
        axis, start, button, rectangle, _ = drag
        end = min(axis.bbox.xmax, max(axis.bbox.xmin, event.x))
        if event.button != button or abs(end - start) < 5 or axis.bbox.width <= 0:
            return
        fraction = (end - start) / axis.bbox.width
        if rectangle:
            factor = abs(fraction) if button == MouseButton.LEFT else 1 / abs(fraction)
        else:
            factor = 10 ** -fraction
        if self._nav_stack() is None:
            self.push_current()
        if self._seek_on_zoom is not None:
            anchor = (start + end) / 2 if rectangle else end
            time = axis.transData.inverted().transform((anchor, axis.bbox.ymin))[0]
            self._seek_on_zoom(time)
        self._scale_view(factor)
        self.push_current()
