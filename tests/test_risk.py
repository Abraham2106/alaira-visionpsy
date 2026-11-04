# Verifica la función pura con poses de pie, sentadas, en caída y con pérdida de señal.
import math
from dataclasses import replace

import pytest

from backend.config import RiskConfig
from backend.interfaces import Landmark, Pose
from backend.model_loader import synthetic_pose
from backend.risk import assess, hip_drop_speed, point_in_polygon, torso_angle_deg


def torso_pose(angle: float, aspect: float) -> Pose:
    points = list(synthetic_pose(0).landmarks)
    drop = 0.2
    dx = math.tan(math.radians(angle)) * drop / aspect
    for index in (11, 12):
        points[index] = Landmark(0.5, 0.4)
    for index in (23, 24):
        points[index] = Landmark(0.5 + dx, 0.6)
    return Pose(tuple(points), 0, aspect)


def series(lying=False, seconds=7):
    return [synthetic_pose(index / 5, lying) for index in range(seconds * 5 + 1)]


def shift(pose, dx=0, dy=0, joints=(11, 12, 23, 24)):
    points = list(pose.landmarks)
    for index in joints:
        point = points[index]
        points[index] = replace(point, x=point.x + dx, y=point.y + dy)
    return replace(pose, landmarks=tuple(points))


def test_standing_and_empty():
    assert assess(series(), RiskConfig()).level == "ok"
    assert assess([], RiskConfig()).reasons == ("no_pose",)


def test_sitting_slowly_stays_ok():
    poses = [shift(synthetic_pose(index / 5), dy=min(index / 150, 0.2)) for index in range(36)]
    assert assess(poses, RiskConfig()).level == "ok"


def test_simulated_fall_becomes_critical_only_after_immobility():
    cfg = RiskConfig()
    poses = series() + [synthetic_pose(7.2 + index / 5, True) for index in range(31)]
    assert assess(poses[:39], cfg).level == "suspect"
    assert assess(poses, cfg).level == "critical"
    assert assess(poses, cfg).reasons == ("horizontal_torso", "immobile")


def test_fast_hip_drop_is_suspect():
    poses = [synthetic_pose(0), shift(synthetic_pose(0.2), dy=0.2)]
    assert hip_drop_speed(poses, 1) == pytest.approx(1)
    assert assess(poses, RiskConfig()).reasons == ("fast_hip_drop",)


def test_safe_zone_including_boundary_suppresses_risk():
    cfg = RiskConfig(safe_zones=[[(0.1, 0.6), (0.9, 0.6), (0.9, 0.95), (0.1, 0.95)]])
    assert assess(series(True), cfg).reasons == ("safe_zone",)
    assert point_in_polygon((0.1, 0.6), cfg.safe_zones[0])
    assert not point_in_polygon((0, 0), cfg.safe_zones[0])
    assert not point_in_polygon((0, 0), [])


def test_shoulder_movement_prevents_immobility_even_with_fixed_hips():
    poses = [shift(pose, dy=0.05 if index % 2 else 0, joints=(11, 12))
             for index, pose in enumerate(series(True))]
    assert assess(poses, RiskConfig()).level == "suspect"


def test_missing_low_visibility_and_capture_gaps_are_not_immobility():
    cfg = RiskConfig()
    poses = series(True)
    invisible = replace(poses[-1], landmarks=tuple(Landmark(p.x, p.y, 0) for p in poses[-1].landmarks))
    assert assess([*poses, invisible], cfg).reasons == ("no_pose",)
    assert assess([synthetic_pose(0, True), synthetic_pose(6, True)], cfg).level == "suspect"
    assert assess([*poses, synthetic_pose(1, True)], cfg).level == "suspect"


def test_assessment_is_pure_and_angles_are_relative_to_vertical():
    poses, cfg = series(True), RiskConfig()
    before = list(poses)
    assert assess(poses, cfg) == assess(poses, cfg)
    assert poses == before
    assert torso_angle_deg(synthetic_pose(0)) == pytest.approx(0)
    assert torso_angle_deg(synthetic_pose(0, True)) == pytest.approx(90)


@pytest.mark.parametrize("aspect", [1, 4 / 3, 16 / 9])
def test_same_physical_angle_at_each_supported_frame_aspect(aspect):
    assert torso_angle_deg(torso_pose(60, aspect)) == pytest.approx(60)


def test_torso_angle_corrects_normalized_coordinates_with_frame_aspect():
    assert torso_angle_deg(torso_pose(60, 16 / 9)) == pytest.approx(60)
    assert torso_angle_deg(torso_pose(60, 1)) == pytest.approx(60)
    # Las mismas coordenadas en un frame 1:1 representan un ángulo físico menor.
    same_points_square_frame = replace(torso_pose(60, 16 / 9), aspect=1.0)
    assert torso_angle_deg(same_points_square_frame) == pytest.approx(44.26, abs=0.01)
    # Un aspecto inválido no rompe la evaluación: se usa el cuadrado como respaldo.
    assert torso_angle_deg(replace(same_points_square_frame, aspect=0)) == pytest.approx(44.26, abs=0.01)
