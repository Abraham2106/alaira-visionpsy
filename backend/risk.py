# Evaluación pura sobre una ventana de poses: geometría, descenso, inmovilidad y zonas seguras.
import math
from dataclasses import dataclass
from typing import Sequence

from .config import RiskConfig
from .interfaces import Pose
from .messages import Level

JOINTS = (11, 12, 23, 24)


@dataclass(frozen=True)
class Assessment:
    level: Level
    reasons: tuple[str, ...]


def _mid(pose: Pose, a: int, b: int) -> tuple[float, float]:
    left, right = pose.landmarks[a], pose.landmarks[b]
    return (left.x + right.x) / 2, (left.y + right.y) / 2


def torso_angle_deg(pose: Pose) -> float:
    sx, sy = _mid(pose, 11, 12)
    hx, hy = _mid(pose, 23, 24)
    aspect = pose.aspect if math.isfinite(pose.aspect) and pose.aspect > 0 else 1.0
    return math.degrees(math.atan2(abs(sx - hx) * aspect, hy - sy))


def point_in_polygon(point: tuple[float, float], polygon: Sequence) -> bool:
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, [*polygon[1:], polygon[0]]):
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) < 1e-10 and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
            return True
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _usable(pose: Pose, cfg: RiskConfig) -> bool:
    return len(pose.landmarks) == 33 and math.isfinite(pose.timestamp) and all(
        math.isfinite(pose.landmarks[i].x) and math.isfinite(pose.landmarks[i].y)
        and pose.landmarks[i].visibility >= cfg.min_visibility for i in JOINTS)


def _contiguous(poses: Sequence[Pose], cfg: RiskConfig) -> list[Pose]:
    window: list[Pose] = []
    for pose in poses:
        if not _usable(pose, cfg):
            window.clear()
            continue
        if window and not (0 < pose.timestamp - window[-1].timestamp <= cfg.max_pose_gap_seconds):
            window.clear()
        window.append(pose)
    return window


def hip_drop_speed(poses: Sequence[Pose], seconds: float) -> float:
    if len(poses) < 2:
        return 0
    recent = [pose for pose in poses if pose.timestamp >= poses[-1].timestamp - seconds]
    if len(recent) < 2:
        return 0
    elapsed = recent[-1].timestamp - recent[0].timestamp
    return max(0, (_mid(recent[-1], 23, 24)[1] - _mid(recent[0], 23, 24)[1]) / elapsed) if elapsed > 0 else 0


def is_immobile(poses: Sequence[Pose], cfg: RiskConfig) -> bool:
    cutoff = poses[-1].timestamp - cfg.immobile_seconds
    if poses[0].timestamp > cutoff + 1e-9:
        return False
    # Incluye la muestra anterior al corte para comprobar la duración completa.
    start = max(index for index, pose in enumerate(poses) if pose.timestamp <= cutoff + 1e-9)
    latest = poses[-1]
    return all(math.hypot(pose.landmarks[i].x - latest.landmarks[i].x,
                          pose.landmarks[i].y - latest.landmarks[i].y) <= cfg.motion_epsilon
               for pose in poses[start:] for i in JOINTS)


def assess(poses: Sequence[Pose], cfg: RiskConfig) -> Assessment:
    window = _contiguous(poses, cfg)
    if not window:
        return Assessment("ok", ("no_pose",))
    if any(point_in_polygon(_mid(window[-1], 23, 24), zone) for zone in cfg.safe_zones):
        return Assessment("ok", ("safe_zone",))
    horizontal = torso_angle_deg(window[-1]) >= cfg.torso_angle_deg
    fast_drop = hip_drop_speed(window, cfg.drop_window_seconds) >= cfg.hip_drop_speed
    immobile = horizontal and is_immobile(window, cfg)
    reasons = tuple(name for name, active in (("horizontal_torso", horizontal),
                    ("fast_hip_drop", fast_drop), ("immobile", immobile)) if active)
    return Assessment("critical" if immobile else "suspect" if horizontal or fast_drop else "ok", reasons)
