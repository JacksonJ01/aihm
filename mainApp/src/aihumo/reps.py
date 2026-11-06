from __future__ import annotations
from dataclasses import dataclass

@dataclass
class RepState:
    phase: str = "unknown"
    completed_reps: int = 0
    saw_concentric: bool = False
    saw_top: bool = False
    saw_eccentric: bool = False

class RepCounter:
    """Simple phase-cycle counter.

    Expected canonical order:
    bottom -> concentric -> top -> eccentric -> bottom

    This is intentionally separate from the CNN so that thresholds and smoothing
    can be changed without retraining the classifier.
    """
    def __init__(self):
        self.state = RepState()

    def update(self, phase: str) -> int:
        if phase == "concentric":
            self.state.saw_concentric = True
        elif phase == "top" and self.state.saw_concentric:
            self.state.saw_top = True
        elif phase == "eccentric" and self.state.saw_top:
            self.state.saw_eccentric = True
        elif phase == "bottom" and self.state.saw_eccentric:
            self.state.completed_reps += 1
            self.state = RepState(phase="bottom")

        self.state.phase = phase
        return self.state.completed_reps
