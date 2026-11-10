"""Interactive, read-only Mode 0 quality review for an existing Parquet."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
)

from aihumo.quality import build_quality_report


class QualityReviewDialog(QDialog):
    """Review saved feature quality without changing the canonical Parquet."""

    def __init__(self, parent=None, *, parquet_path: str | Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("AIHuMo — Quality Review")
        self.resize(820, 620)
        self.parquet_path = Path(parquet_path) if parquet_path else None
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Read-only checks for timestamps, pose availability, feature missingness, "
            "visibility, and tracking status. The source Parquet is never rewritten."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        path_row = QHBoxLayout()
        self.path_label = QLabel(str(self.parquet_path) if self.parquet_path else "No Parquet selected")
        self.path_label.setTextInteractionFlags(self.path_label.textInteractionFlags())
        choose = QPushButton("Choose Parquet…")
        choose.clicked.connect(self.choose_parquet)
        path_row.addWidget(self.path_label, 1)
        path_row.addWidget(choose)
        form.addRow("Feature data", path_row)
        layout.addLayout(form)
        self.summary = QTextBrowser()
        self.summary.setOpenExternalLinks(False)
        layout.addWidget(self.summary, 1)
        self.missing_table = QTableWidget(0, 2)
        self.missing_table.setHorizontalHeaderLabels(("Feature", "Missing fraction"))
        self.missing_table.setAlternatingRowColors(True)
        self.missing_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(QLabel("Most incomplete features"))
        layout.addWidget(self.missing_table)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        if self.parquet_path:
            self.refresh()

    def choose_parquet(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select feature Parquet", "", "Parquet (*.parquet)")
        if path:
            self.parquet_path = Path(path)
            self.path_label.setText(str(self.parquet_path))
            self.refresh()

    def refresh(self) -> None:
        if not self.parquet_path or not self.parquet_path.is_file():
            self.summary.setText("Choose an existing feature Parquet to begin.")
            return
        try:
            names = pq.read_schema(self.parquet_path).names
            dataframe = pd.read_parquet(self.parquet_path, columns=names)
            report = build_quality_report(dataframe)
        except Exception as exc:
            self.summary.setText(f"Could not read the selected Parquet.\n\n{type(exc).__name__}: {exc}")
            self.missing_table.setRowCount(0)
            return
        timestamp = report.get("timestamp", {})
        lines = [
            f"Frames: {report['frame_count']:,}",
            f"Features: {report['feature_count']:,}",
            f"Duration: {timestamp.get('duration_s', 0.0):,.3f} s",
            f"Pose present: {report['pose_present_fraction']:.1%}",
            f"Pose missing: {report['pose_missing_fraction']:.1%}",
        ]
        tracking = report.get("target_tracking")
        if tracking:
            lines.extend((
                f"Tracked/reacquired: {tracking['tracked_fraction']:.1%}",
                f"Occluded: {tracking['occluded_fraction']:.1%}",
                f"Lost: {tracking['lost_fraction']:.1%}",
            ))
        self.summary.setText("\n".join(lines))
        missing = report.get("highest_missing_features", [])
        self.missing_table.setRowCount(len(missing))
        for row, item in enumerate(missing):
            self.missing_table.setItem(row, 0, QTableWidgetItem(str(item["feature"])))
            self.missing_table.setItem(row, 1, QTableWidgetItem(f"{float(item['nan_fraction']):.1%}"))
