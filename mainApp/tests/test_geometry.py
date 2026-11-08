import numpy as np
from aihumo.geometry import angle_degrees


def test_right_angle(detail):
    points = ([1, 0, 0], [0, 0, 0], [0, 1, 0])
    detail(input=points, expected="90 degrees")
    angle = angle_degrees(*(np.array(point) for point in points))
    detail(observed=f"{angle:.2f} degrees")
    assert np.isclose(angle, 90.0)


def test_degenerate_angle(detail):
    points = ([0, 0, 0], [0, 0, 0], [1, 0, 0])
    detail(input=points, expected="NaN for a zero-length angle arm")
    angle = angle_degrees(*(np.array(point) for point in points))
    detail(observed=angle)
    assert np.isnan(angle)
