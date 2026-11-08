"""Source-timed video playback shared by the desktop workspaces."""
from __future__ import annotations

from math import isfinite
from time import monotonic
from typing import Callable, Sequence

from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtWidgets import QPushButton, QWidget


class FramePlayback(QObject):
    def __init__(
        self, parent: QWidget, *, timestamps: Sequence[float], position: Callable[[], int],
        display_frame: Callable[[int], bool], refresh_thumbnails: Callable[[], None], fps: float = 30.0,
    ):
        super().__init__(parent)
        self.timestamps = timestamps
        self.position = position
        self.display_frame = display_frame
        self.refresh_thumbnails = refresh_thumbnails
        self.fallback_interval = 1 / (fps if isfinite(fps) and fps > 0 else 30.0)
        self.playing = False
        self._deadline = 0.0
        self.button = QPushButton("Pause", parent)
        self.button.setMinimumWidth(self.button.sizeHint().width())
        self.button.setText("Play")
        self.button.clicked.connect(self.toggle)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)

    def toggle(self) -> None:
        if self.playing:
            self.pause()
            return
        self.playing = True
        self.button.setText("Pause")
        if self.position() == len(self.timestamps) - 1 and not self.display_frame(0):
            self.pause()
            return
        self._deadline = monotonic()
        self._schedule_next_frame()

    def _schedule_next_frame(self) -> None:
        index = self.position()
        if index + 1 >= len(self.timestamps):
            self.pause()
            return
        elapsed = float(self.timestamps[index + 1] - self.timestamps[index])
        if not isfinite(elapsed) or elapsed <= 0:
            elapsed = self.fallback_interval
        # Carry the deadline forward so ordinary decoding and painting time
        # does not accumulate as a playback delay on every frame.
        self._deadline += elapsed
        delay = min(max(0.0, self._deadline - monotonic()), 2_147_483.647)
        self.timer.start(max(1, round(delay * 1000)))

    def advance(self) -> None:
        if self.playing:
            if self.display_frame(self.position() + 1):
                self._schedule_next_frame()
            else:
                self.pause()

    def pause(self, *, refresh: bool = True) -> None:
        if self.playing:
            self.playing = False
            self.timer.stop()
            self.button.setText("Play")
            if refresh:
                self.refresh_thumbnails()
