"""Temporal evidence per camera. Independent implementation; no external project code."""
from collections import deque
from dataclasses import dataclass
import math

from .config import RiskConfig
from .interfaces import Pose
from .risk import Assessment, point_in_polygon


@dataclass(frozen=True)
class Features:
    at: float
    x: float
    y: float
    angle: float
    scale: float
    partial: bool
    body_horizontal: bool | None
    aspect: float


def features(pose: Pose | None, now: float, cfg: RiskConfig) -> Features | None:
    if pose is None or len(pose.landmarks) != 33 or not math.isfinite(now):
        return None
    def visible(index):
        p = pose.landmarks[index]
        return (math.isfinite(p.x) and math.isfinite(p.y) and math.isfinite(p.visibility)
                and p.visibility >= cfg.min_visibility and 0 <= p.x <= 1 and 0 <= p.y <= 1)
    # Prefer a complete anatomical side, rather than inventing an invisible joint.
    pairs = [(s, h) for s, h in ((11, 23), (12, 24)) if visible(s) and visible(h)]
    if not pairs:
        return None
    sx = sum(pose.landmarks[s].x for s, _ in pairs) / len(pairs)
    sy = sum(pose.landmarks[s].y for s, _ in pairs) / len(pairs)
    hx = sum(pose.landmarks[h].x for _, h in pairs) / len(pairs)
    hy = sum(pose.landmarks[h].y for _, h in pairs) / len(pairs)
    aspect = pose.aspect if math.isfinite(pose.aspect) and pose.aspect > 0 else 1
    length = math.hypot((sx-hx)*aspect, sy-hy)
    if length < 0.03:
        return None
    ankles = [pose.landmarks[i] for i in (27, 28) if visible(i)]
    body_horizontal = None
    if ankles:
        ax, ay = sum(p.x for p in ankles)/len(ankles), sum(p.y for p in ankles)/len(ankles)
        body_horizontal = math.degrees(math.atan2(abs(sx-ax)*aspect, ay-sy)) >= cfg.torso_angle_deg
    return Features(now, hx, hy, math.degrees(math.atan2(abs(sx-hx)*aspect, hy-sy)), length, len(pairs) == 1, body_horizontal, aspect)


class TemporalFallDetector:
    def __init__(self):
        self.reset()

    def reset(self):
        self.phase = "UPRIGHT"
        self.history = deque(maxlen=256)
        self.observed_down = 0.0
        self.fast_candidate = False
        self.down_anchor = None
        self.last_valid = None
        self.config = None
        self.interrupted = False
        self.quality = "missing"
        self.vertical_speed = 0.0
        self.angular_speed = 0.0
        self.fps = 0.0
        self.candidate_at = None

    def diagnostics(self):
        return {"phase": self.phase, "quality": self.quality,
                "angle_deg": round(self.history[-1].angle, 1) if self.history and self.quality != "missing" else None,
                "vertical_speed": round(self.vertical_speed, 2), "angular_speed": round(self.angular_speed, 1),
                "observed_seconds": round(self.observed_down, 2), "fps": round(self.fps, 1)}

    def update(self, pose: Pose | None, now: float, cfg: RiskConfig) -> Assessment:
        if self.config is not None and self.config != cfg:
            self.reset()
        self.config = cfg
        current = features(pose, now, cfg)
        grace = min(cfg.pose_grace_seconds, cfg.max_pose_gap_seconds)
        if current is None:
            if self.last_valid is not None and now-self.last_valid > grace:
                self.reset()
                self.config = cfg
            self.quality = "missing"
            self.interrupted = True
            return Assessment("ok" if self.phase == "UPRIGHT" else "suspect", ("no_pose", "pose_gap"))
        previous = self.history[-1] if self.history else None
        gap = now-previous.at if previous else 0
        if previous and not 0 < gap <= grace:
            self.reset()
            self.config = cfg
            previous = None
        self.last_valid = now
        self.quality = "partial" if current.partial else "complete"
        self.fps = 1/gap if previous and gap > 0 else 0
        self.history.append(current)
        while len(self.history) > 1 and now-self.history[0].at > cfg.drop_window_seconds:
            self.history.popleft()
        reference = self.history[0]
        elapsed = now-reference.at
        speed = (current.y-reference.y)/max(reference.scale, .03)/elapsed if elapsed > 0 else 0
        angular = (current.angle-reference.angle)/elapsed if elapsed > 0 else 0
        self.vertical_speed, self.angular_speed = speed, angular
        tilted = current.angle >= cfg.torso_angle_deg
        lower = current.y-reference.y >= reference.scale*.15
        fast = speed >= cfg.body_drop_speed or (angular >= cfg.angular_velocity_deg_s and lower)
        in_zone = any(point_in_polygon((current.x, current.y), zone) for zone in cfg.safe_zones)
        reasons = ["partial_pose"] if current.partial else []
        if tilted:
            reasons.append("horizontal_torso")
        if speed >= cfg.body_drop_speed:
            reasons.append("fast_hip_drop")
        if angular >= cfg.angular_velocity_deg_s:
            reasons.append("fast_rotation")
        if current.angle <= cfg.recovery_angle_deg:
            self.phase = "UPRIGHT"
            self.observed_down = 0
            self.fast_candidate = False
            self.down_anchor = None
            self.candidate_at = None
            return Assessment("suspect" if fast else "ok", tuple(reasons))
        if self.phase == "FALL_CONFIRMED":
            return Assessment("critical", tuple([*reasons, "fall_confirmed"]))
        if self.phase == "FALLING" and self.candidate_at is not None and now-self.candidate_at > cfg.transition_seconds:
            self.phase = "UPRIGHT"
            self.fast_candidate = False
            self.candidate_at = None
        if fast:
            self.fast_candidate = True
            if self.phase == "UPRIGHT":
                self.phase = "FALLING"
                self.candidate_at = now
        if tilted and current.body_horizontal is not False:
            if self.phase not in {"DOWN", "FALL_CONFIRMED"}:
                self.phase = "DOWN"
                self.down_anchor = current
                self.observed_down = 0
            elif previous and not self.interrupted:
                # Missing samples do not count as observed time on the floor.
                self.observed_down += gap
            self.interrupted = False
            anchor = self.down_anchor or current
            motion = math.hypot((current.x-anchor.x)*current.aspect, current.y-anchor.y)
            stable = motion <= max(cfg.motion_epsilon, current.scale*.12)
            if not self.fast_candidate and not stable:
                self.observed_down = 0
                self.down_anchor = current
            # A bed/chair is context, not immunity to an observed abrupt transition.
            if in_zone and not self.fast_candidate and self.phase != "FALL_CONFIRMED":
                self.observed_down = 0
                return Assessment("ok", tuple([*reasons, "safe_zone"]))
            if not self.fast_candidate and current.body_horizontal is None and self.phase != "FALL_CONFIRMED":
                self.observed_down = 0
                return Assessment("suspect", tuple([*reasons, "floor_context_missing"]))
            required = cfg.confirm_seconds if self.fast_candidate else cfg.immobile_seconds
            if self.phase == "FALL_CONFIRMED" or self.observed_down + 1e-9 >= required:
                self.phase = "FALL_CONFIRMED"
                evidence = "fall_transition" if self.fast_candidate else "immobile"
                return Assessment("critical", tuple([*reasons, evidence, "fall_confirmed"]))
        elif self.phase == "DOWN":
            self.observed_down = 0
            if self.candidate_at is not None and now-self.candidate_at > cfg.transition_seconds:
                self.fast_candidate = False
        return Assessment("suspect" if self.phase != "UPRIGHT" or tilted else "ok", tuple([*reasons, self.phase.lower()]))
