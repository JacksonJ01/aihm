"""Capture the Mode 0 inputs used by the existing job recovery flow."""
from PyQt6.QtCore import QSignalBlocker


_COMMON_FIELDS = (
    "model", "session", "video_id", "participant", "camera_id", "camera_name",
    "recording_date", "exercise", "viewpoint", "environment", "operator", "output",
)


def processing_fields(dialog):
    fields = {name: getattr(dialog, f"{name}_edit").text() for name in _COMMON_FIELDS
              if hasattr(dialog, f"{name}_edit")}
    fields.update(notes=dialog.notes_edit.toPlainText(), cameraAngle=dialog.camera_angle_combo.currentData(),
                  openAnnotation=dialog.open_mode1_check.isChecked())
    return fields


def restore_processing_fields(dialog, fields):
    for name in _COMMON_FIELDS:
        edit = getattr(dialog, f"{name}_edit", None)
        if edit is not None and isinstance(fields.get(name), str):
            with QSignalBlocker(edit):
                edit.setText(fields[name])
    dialog.notes_edit.setPlainText(str(fields.get("notes", "")))
    index = dialog.camera_angle_combo.findData(fields.get("cameraAngle"))
    if index >= 0:
        dialog.camera_angle_combo.setCurrentIndex(index)
    dialog.open_mode1_check.setChecked(bool(fields.get("openAnnotation", True)))
