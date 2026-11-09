from __future__ import annotations

import numpy as np
import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget


class ReviewWindow(QMainWindow):
    """Keep a workspace's state while another mode owns playback."""

    review_suspended = False

    def suspend_review(self):
        self.review_suspended = True
        self._pause_review()

    def resume_review(self):
        self.review_suspended = False
        self._resume_review()

    def activate_review(self):
        suspend_other_reviews(self)
        self.resume_review()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isWindow() and self.isActiveWindow():
            self.activate_review()


def suspend_other_reviews(target=None):
    for window in QApplication.topLevelWidgets():
        if isinstance(window, ReviewWindow) and window is not target and window.isVisible():
            window.suspend_review()


def close_and_return(window: QWidget, target: QWidget | None = None) -> None:
    """Return to the window that opened this one after an accepted close."""
    parent = target if target is not None else window.parentWidget()
    if not window.close() or parent is None:
        return
    if parent.isMinimized():
        parent.setWindowState(parent.windowState() & ~Qt.WindowState.WindowMinimized)
    if isinstance(parent, ReviewWindow):
        parent.activate_review()
    parent.show()
    parent.raise_()
    parent.activateWindow()


class DataFrameModel(QAbstractTableModel):
    """Small read-only Qt model for displaying pandas DataFrames."""

    def __init__(self, dataframe: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._dataframe = dataframe if dataframe is not None else pd.DataFrame()

    def set_dataframe(self, dataframe: pd.DataFrame) -> None:
        self.beginResetModel()
        self._dataframe = dataframe
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._dataframe)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._dataframe.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        value = self._dataframe.iloc[index.row(), index.column()]
        if pd.isna(value):
            return ""
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.5f}"
        return str(value)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._dataframe.columns[section])
        return str(self._dataframe.index[section])
