import numpy as np
from aihumo.geometry import angle_degrees


def test_right_angle():
    assert np.isclose(angle_degrees(np.array([1, 0, 0]), np.array([0, 0, 0]), np.array([0, 1, 0])), 90.0)


def test_degenerate_angle():
    assert np.isnan(angle_degrees(np.array([0, 0, 0]), np.array([0, 0, 0]), np.array([1, 0, 0])))
