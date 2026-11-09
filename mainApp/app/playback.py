"""Source-timed video playback shared by the desktop workspaces."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from math import isfinite
from pathlib import Path
from threading import Condition, Thread
from time import monotonic
from typing import Callable, Sequence

import cv2
import numpy as np
from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton, QWidget


class PlaybackSpeed(QObject):
    changed = pyqtSignal(int)
    OPTIONS = tuple(i / 10 for i in range(1, 10)) + tuple(range(1, 11))

    def __init__(self, parent):
        super().__init__(parent)
        self.value = 1.0

    def control(self):
        combo = QComboBox()
        combo.setAccessibleName("Playback speed")
        combo.setToolTip("Playback speed for Play and when holding a Jump button.")
        for speed in self.OPTIONS:
            combo.addItem(f"{speed:g}×", float(speed))
        combo.setCurrentIndex(combo.findData(self.value))
        combo.currentIndexChanged.connect(self._select)
        self.changed.connect(combo.setCurrentIndex)
        return combo

    def _select(self, index):
        if index >= 0 and self.OPTIONS[index] != self.value:
            self.value = float(self.OPTIONS[index])
            self.changed.emit(index)


class FrameNavigationButton(QPushButton):
    """Tap to seek once, or hold to shuttle until released."""

    def __init__(self, text, *, playback, pause, seek, direction, jump=False):
        super().__init__(text)
        self.playback = playback
        self._pause = pause
        self._seek = seek
        self._direction = direction
        self._jump = jump
        self._held = False
        self._hold_timer = QTimer(self, interval=3000, singleShot=True, timerType=Qt.TimerType.PreciseTimer)
        self._hold_timer.timeout.connect(self._start_hold)
        self.pressed.connect(self._press)
        self.released.connect(self._release)
        self.clicked.connect(self._tap)
        speed = "the selected speed" if jump else "1×"
        self.setToolTip(f"Tap to seek once. Hold for 3 seconds to play at {speed} until released.")

    def _press(self):
        self._pause()
        self._held = False
        self._hold_timer.start()

    def _start_hold(self):
        window = self.window()
        if self.isDown() and self.isVisible() and window.isActiveWindow() and not window.isMinimized():
            self._held = True
            self.playback.start(direction=self._direction, hold=True, speed=None if self._jump else 1.0)

    def _release(self):
        self._hold_timer.stop()
        if self._held and self.playback.holding:
            self.playback.pause()

    def _tap(self):
        if not self._held:
            self._seek()

    def hideEvent(self, event):
        self._release()
        super().hideEvent(event)

    def focusOutEvent(self, event):
        self._release()
        super().focusOutEvent(event)


def review_window_is_covered(widget: QWidget) -> bool:
    window = widget.window()
    if not window.isVisible() or window.isMinimized():
        return True
    active = QApplication.activeWindow()
    return active is not None and active is not window and active.frameGeometry().contains(window.frameGeometry())


def decode_frame(capture, index: int):
    """Use sequential decoding for small forward jumps during playback."""
    if isinstance(capture, TimestampedCapture):
        return capture.read_frame(index)
    distance = index - int(capture.get(cv2.CAP_PROP_POS_FRAMES))
    if 0 <= distance <= 24:
        for _ in range(distance):
            if not capture.grab():
                return False, None
    elif not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
        return False, None
    return capture.read()


def fit_video_pixmap(frame: np.ndarray, width: int, height: int) -> QPixmap:
    """Fit a video frame to its display area before allocating a Qt pixmap."""
    rows, columns = frame.shape[:2]
    scale = min(width / columns, height / rows)
    width, height = max(1, round(columns * scale)), max(1, round(rows * scale))
    small = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
    image = QImage(small.data, width, height, small.strides[0], QImage.Format.Format_BGR888)
    return QPixmap.fromImage(image)


def _open_playback_capture(path, *, decoder_threads=1):
    threads = getattr(cv2, "CAP_PROP_N_THREADS", None)
    if threads is not None:
        capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG, [threads, decoder_threads])
        if capture.isOpened():
            return capture
        capture.release()
    return cv2.VideoCapture(str(path))


class TimestampedCapture:
    """Seek a variable-rate clean source using the saved native frame clock."""

    def __init__(self, capture, timestamps):
        self.capture = capture
        self.timestamps = timestamps
        self._next_index = 0

    def get(self, property_id):
        return self.capture.get(property_id)

    def isOpened(self):
        return self.capture.isOpened()

    def release(self):
        self.capture.release()

    def read_frame(self, index):
        expected = self.timestamps[index]
        distance = index - self._next_index if self._next_index is not None else -1
        self._next_index = None
        if 0 <= distance <= 24 and all(self.capture.grab() for _ in range(distance)):
            ok, image = self.capture.read()
            if ok and abs(self.capture.get(cv2.CAP_PROP_POS_MSEC) / 1000 - expected) <= 0.002:
                self._next_index = index + 1
                return True, image
        # A backend can round a timestamp seek to the next frame. If so,
        # seek slightly earlier and decode forward to the exact saved time.
        for start in (expected, self.timestamps[max(0, index - 8)]):
            if not self.capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000):
                continue
            for _ in range(24):
                ok, image = self.capture.read()
                if not ok:
                    break
                actual = self.capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if abs(actual - expected) <= 0.002:
                    self._next_index = index + 1
                    return True, image
                if not isfinite(actual) or actual > expected:
                    break
        return False, None


def open_review_video(path: Path, metadata: dict, frame_count: int, *, timestamps=None):
    """Prefer the recorded clean source when its identity and frame mapping match."""
    processed = metadata.get("processed_video")
    registered = bool(processed and Path(processed).resolve() == path.resolve())
    baked = registered or path.stem.endswith("_skeleton")
    source = metadata.get("source_video")
    fingerprint = metadata.get("source_fingerprint", {})
    if registered and source and fingerprint.get("size_bytes") is not None:
        clean = Path(source)
        if clean.is_file() and clean.resolve() != path.resolve():
            info = clean.stat()
            if info.st_size == fingerprint["size_bytes"] and info.st_mtime_ns == fingerprint.get("modified_ns"):
                capture = _open_playback_capture(clean)
                size = metadata.get("resolution", {})
                if (capture.isOpened() and int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == frame_count
                        and int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) == size.get("width")
                        and int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) == size.get("height")):
                    fps = capture.get(cv2.CAP_PROP_FPS)
                    if timestamps is not None and isfinite(fps) and fps > 0:
                        times = np.asarray(timestamps, dtype=float)
                        if (len(times) == frame_count and np.isfinite(times).all()
                                and np.any(np.abs(times * fps - np.arange(frame_count)) > 0.75)):
                            capture = TimestampedCapture(capture, times)
                    return capture, clean, False
                capture.release()
    return _open_playback_capture(path), path, baked


class FrameBuffer:
    """One background decoder and a bounded window of native frames per viewer."""

    DEFAULT_MEMORY_LIMIT = 192 * 1024**2
    SELECTED_CAMERA_MEMORY_LIMIT = 384 * 1024**2
    CACHE_WAIT_SECONDS = 0.012

    def __init__(self, path, frame_count: int, frame_size: tuple[int, int], *,
                 memory_limit: int = DEFAULT_MEMORY_LIMIT, selected_memory_limit: int | None = None,
                 timestamps=None):
        self.path = str(path)
        self.frame_count = frame_count
        self._frame_bytes = max(1, frame_size[0] * frame_size[1] * 3)
        self._memory_limit = memory_limit
        self._selected_memory_limit = min(
            self.SELECTED_CAMERA_MEMORY_LIMIT,
            selected_memory_limit if selected_memory_limit is not None else self.SELECTED_CAMERA_MEMORY_LIMIT,
        )
        self._timestamps = timestamps
        self.behind, self.ahead = self._window_size(False)
        self._condition = Condition()
        self._frames: dict[int, np.ndarray] = {}
        self._failed: set[int] = set()
        self._center = 0
        self._playback_direction = 0
        self._urgent_index: int | None = None
        self._decoder_unavailable = False
        self._closed = False
        self._worker = Thread(target=self._decode, name="AIHuMo frame prefetch", daemon=True)
        self._worker.start()

    def _window_size(self, selected):
        budget = self._selected_memory_limit if selected else self._memory_limit
        neighbors = max(0, budget // self._frame_bytes - 1)
        if selected:
            return min(50, neighbors // 2), min(50, (neighbors + 1) // 2)
        behind = min(16, max(neighbors // 4, min(neighbors // 2, 2)))
        return behind, min(48, neighbors - behind)

    def set_selected_camera(self, selected):
        with self._condition:
            size = self._window_size(selected)
            if self._closed or size == (self.behind, self.ahead):
                return
            self.behind, self.ahead = size
            self._trim_window()

    def _bounds(self):
        return max(0, self._center - self.behind), min(self.frame_count, self._center + self.ahead + 1)

    def request(self, index: int, *, playback: bool = False, direction: int = 1) -> None:
        with self._condition:
            self._set_playback_direction(direction if playback else 0)
            self._move_window(index)

    def _set_playback_direction(self, direction):
        if self._playback_direction != direction:
            self._playback_direction = direction
            if direction:
                self._failed.clear()
            self._condition.notify()

    def _move_window(self, index: int) -> None:
        if self._closed or index == self._center:
            return
        self._center = index
        self._trim_window()

    def _trim_window(self):
        low, high = self._bounds()
        for key in tuple(self._frames):
            if not low <= key < high:
                del self._frames[key]
        self._failed.intersection_update(range(low, high))
        if self._urgent_index is not None and not low <= self._urgent_index < high:
            self._urgent_index = None
        self._condition.notify()

    def get(self, index: int) -> np.ndarray | None:
        with self._condition:
            return self._frames.get(index)

    def read(self, capture, index: int):
        with self._condition:
            if self._closed:
                return False, None
            frame = self._frames.get(index)
            if frame is None and not self._decoder_unavailable:
                self._urgent_index = index
                self._move_window(index)
                self._condition.notify()
                self._condition.wait_for(
                    lambda: self._closed or index in self._frames or index in self._failed,
                    timeout=self.CACHE_WAIT_SECONDS,
                )
                frame = self._frames.get(index)
        if frame is not None:
            return True, frame
        ok, frame = decode_frame(capture, index)
        if ok:
            with self._condition:
                low, high = self._bounds()
                if not self._closed and low <= index < high:
                    self._frames[index] = frame
        return ok, frame

    def ready_for_playback(self, target: int, displayed: int) -> int | None:
        """Return the newest due frame in the cache."""
        with self._condition:
            if self._closed:
                return None
            direction = 1 if target > displayed else -1
            self._set_playback_direction(direction)
            capacity = self.ahead if direction > 0 else self.behind
            if self._decoder_unavailable or target in self._failed or capacity == 0:
                return target
            low, high = self._bounds()
            # After a catch-up seek, wait for the requested frame before
            # considering another seek. Chasing the clock can starve decoding.
            candidates = (range(min(target, high - 1), max(displayed + 1, self._center) - 1, -1)
                          if direction > 0 else range(max(target, low), min(displayed - 1, self._center) + 1))
            ready = next((index for index in candidates if index in self._frames), None)
            latest = displayed if ready is None else ready
            if self._center == displayed and abs(target - latest) > max(12, capacity // 2):
                self._move_window(target)
                return None
            return ready

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._frames.clear()
            self._failed.clear()
            self._urgent_index = None
            self._condition.notify()
        self._worker.join(timeout=1)

    def _next_index(self):
        low, high = self._bounds()
        if (self._urgent_index is not None and low <= self._urgent_index < high
                and self._urgent_index not in self._frames and self._urgent_index not in self._failed):
            return self._urgent_index
        if self._playback_direction:
            # Fill in the direction of travel while playback is active.
            candidates = (range(self._center, high) if self._playback_direction > 0
                          else range(self._center, low - 1, -1))
            return next((index for index in candidates
                         if index not in self._frames and index not in self._failed), None)
        for group in (range(self._center, high), range(low, self._center)):
            for index in group:
                if index not in self._frames and index not in self._failed:
                    return index
        return None

    def _decode(self):
        # The prefetch decoder does the sustained sequential work. Foreground
        # captures remain single-threaded exact-seek fallbacks.
        capture = _open_playback_capture(self.path, decoder_threads=2)
        if self._timestamps is not None:
            capture = TimestampedCapture(capture, self._timestamps)
        try:
            if not capture.isOpened():
                with self._condition:
                    self._decoder_unavailable = True
                return
            while True:
                with self._condition:
                    while not self._closed and (index := self._next_index()) is None:
                        self._condition.wait()
                    if self._closed:
                        return
                ok, frame = decode_frame(capture, index)
                with self._condition:
                    if self._closed:
                        return
                    low, high = self._bounds()
                    if low <= index < high:
                        if ok:
                            self._frames[index] = frame
                        else:
                            self._failed.add(index)
                    if self._urgent_index == index:
                        self._urgent_index = None
                    self._condition.notify_all()
        finally:
            capture.release()


class FramePlayback(QObject):
    starting = pyqtSignal()
    paused = pyqtSignal()

    def __init__(
        self, parent: QWidget, *, timestamps: Sequence[float], position: Callable[[], int],
        display_frame: Callable[[int], bool], refresh_paused_frame: Callable[[], None], fps: float = 30.0,
        ready_frame: Callable[[int, int], int | None] | None = None,
    ):
        super().__init__(parent)
        self.timestamps = timestamps
        self.position = position
        self.display_frame = display_frame
        self.refresh_paused_frame = refresh_paused_frame
        self.ready_frame = ready_frame
        self.fallback_interval = 1 / (fps if isfinite(fps) and fps > 0 else 30.0)
        steps = np.diff(np.asarray(timestamps, dtype=float))
        steps = np.where(np.isfinite(steps) & (steps > 0), steps, self.fallback_interval)
        self._offsets = np.r_[0.0, np.cumsum(steps)]
        self.playing = False
        self.holding = False
        self.direction = 1
        self.speed = PlaybackSpeed(self)
        self.speed.changed.connect(self._change_speed)
        self._rate = 1.0
        self._fixed_speed = None
        self._start_offset = 0.0
        self._started_at = 0.0
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
        else:
            self.start()

    def start(self, *, direction=1, hold=False, speed=None) -> None:
        if self.playing:
            self.pause(refresh=False)
        self.starting.emit()
        boundary = len(self.timestamps) - 1 if direction > 0 else 0
        if self.position() == boundary and (hold or direction < 0 or not self.display_frame(0)):
            return
        self.direction, self.holding, self._fixed_speed = direction, hold, speed
        self._rate = self.speed.value if speed is None else speed
        self.playing = True
        self.button.setText("Pause")
        self._rebase_clock()
        self._schedule_next_frame()

    def _rebase_clock(self):
        self._start_offset = self._offsets[self.position()]
        self._started_at = monotonic()

    def _change_speed(self):
        if self.playing and self._fixed_speed is None:
            self._rate = self.speed.value
            self._rebase_clock()
            self._schedule_next_frame()

    def _schedule_next_frame(self) -> None:
        index = self.position() + self.direction
        if not 0 <= index < len(self.timestamps):
            self.pause()
            return
        deadline = self._started_at + abs(self._offsets[index] - self._start_offset) / self._rate
        delay = min(max(0.0, deadline - monotonic()), 2_147_483.647)
        self.timer.start(max(1, round(delay * 1000)))

    def advance(self) -> None:
        if self.playing:
            # When the UI falls behind, show the frame due on the source clock.
            # Frame stepping and annotation seeks still use exact native frames.
            offset = self._start_offset + (monotonic() - self._started_at) * self.direction * self._rate
            current = self.position()
            if self.direction > 0:
                due = bisect_right(self._offsets, offset) - 1
                index = min(len(self.timestamps) - 1, max(current + 1, due))
            else:
                index = max(0, min(current - 1, bisect_left(self._offsets, offset)))
            if self.ready_frame is not None:
                index = self.ready_frame(index, current)
                if index is None:
                    self.timer.start(8)
                    return
            if self.display_frame(index):
                self._schedule_next_frame()
            else:
                self.pause()

    def pause(self, *, refresh: bool = True) -> None:
        if self.playing:
            self.playing = False
            self.holding = False
            self.timer.stop()
            self.button.setText("Play")
            if refresh:
                self.refresh_paused_frame()
                self.paused.emit()
