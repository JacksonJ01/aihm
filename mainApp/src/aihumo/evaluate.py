from __future__ import annotations

from typing import Any

import numpy as np
import torch
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
)


def _classification_metrics(y_true: np.ndarray, y_pred: np.ndarray, id_to_label: dict[int, str]) -> dict[str, Any]:
    mask = y_true >= 0
    y_true = y_true[mask]
    y_pred = y_pred[mask]
    labels = sorted(id_to_label)
    if y_true.size == 0:
        return {"samples": 0}
    # Include only labels observed by the encoding, while still evaluating all
    # known classes so absent test classes remain explicit in the confusion matrix.
    target_names = [id_to_label[i] for i in labels]
    return {
        "samples": int(y_true.size),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "macro_precision": float(precision_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "classification_report": classification_report(
            y_true, y_pred, labels=labels, target_names=target_names,
            output_dict=True, zero_division=0,
        ),
    }


def _binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    mask = y_true >= 0
    y_true = y_true[mask].astype(np.int64)
    y_pred = y_pred[mask].astype(np.int64)
    if y_true.size == 0:
        return {"samples": 0}
    return {
        "samples": int(y_true.size),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist(),
    }


def evaluate_multitask_model(
    model,
    loader,
    device,
    label_mappings: dict[str, dict[str, int]],
    target_specs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    model.eval()
    collected_true: dict[str, list[np.ndarray]] = {}
    collected_pred: dict[str, list[np.ndarray]] = {}
    collected_reg_true: dict[str, list[np.ndarray]] = {}
    collected_reg_pred: dict[str, list[np.ndarray]] = {}

    with torch.no_grad():
        for x, targets, _ in loader:
            x = x.to(device)
            outputs = model(x)
            for name, prediction in outputs.items():
                task = target_specs[name].get("task")
                if task in {"classification", "sequence_classification"}:
                    collected_true.setdefault(name, []).append(targets[name].cpu().numpy().reshape(-1))
                    collected_pred.setdefault(name, []).append(prediction.argmax(dim=-1).cpu().numpy().reshape(-1))
                elif task == "sequence_binary":
                    collected_true.setdefault(name, []).append(targets[name].cpu().numpy().reshape(-1))
                    collected_pred.setdefault(name, []).append((torch.sigmoid(prediction) >= 0.5).cpu().numpy().astype(np.int64).reshape(-1))
                elif task == "regression":
                    true = targets[name].cpu().numpy().reshape(-1)
                    pred = prediction.cpu().numpy().reshape(-1)
                    mask = np.isfinite(true)
                    if mask.any():
                        collected_reg_true.setdefault(name, []).append(true[mask])
                        collected_reg_pred.setdefault(name, []).append(pred[mask])

    results: dict[str, Any] = {"targets": {}}
    for name, values in collected_true.items():
        y_true = np.concatenate(values)
        y_pred = np.concatenate(collected_pred[name])
        task = target_specs[name].get("task")
        if task == "sequence_binary":
            results["targets"][name] = _binary_metrics(y_true, y_pred)
        else:
            mapping = label_mappings.get(name, {})
            id_to_label = {value: key for key, value in mapping.items()}
            results["targets"][name] = _classification_metrics(y_true, y_pred, id_to_label)

    for name, values in collected_reg_true.items():
        true = np.concatenate(values)
        pred = np.concatenate(collected_reg_pred[name])
        results["targets"][name] = {
            "samples": int(len(true)),
            "mae": float(mean_absolute_error(true, pred)),
            "rmse": float(np.sqrt(mean_squared_error(true, pred))),
        }
    return results


def evaluate_model(model, loader, device, id_to_label: dict[int, str]):
    """Compatibility evaluator for the old exercise-only baseline."""
    model.eval()
    y_true, y_pred = [], []
    with torch.no_grad():
        for x, y, _ in loader:
            x = x.to(device)
            logits = model(x)
            y_true.extend(y.numpy().tolist())
            y_pred.extend(logits.argmax(dim=1).cpu().numpy().tolist())
    return _classification_metrics(np.asarray(y_true), np.asarray(y_pred), id_to_label)
