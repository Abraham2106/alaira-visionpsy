from dataclasses import replace

import pytest

from backend.config import RiskConfig
from backend.fall_detector import TemporalFallDetector, features
from backend.model_loader import synthetic_pose


def hidden(pose, joints):
    return replace(pose, landmarks=tuple(replace(p, visibility=0) if i in joints else p for i,p in enumerate(pose.landmarks)))


@pytest.mark.parametrize("fps",[5,24,30])
def test_fast_fall_with_postfall_motion_and_partial_pose(fps):
    detector=TemporalFallDetector()
    cfg=RiskConfig()
    results=[]
    for i in range(4*fps+1):
        t=i/fps
        pose=synthetic_pose(t,t>=1)
        if t>=1:
            # A visible anatomical side is enough; motion does not cancel the witnessed transition.
            pose=hidden(pose,(11,23))
            pose=replace(pose,landmarks=tuple(replace(p,x=p.x+(.025 if i%2 else 0)) for p in pose.landmarks))
        results.append(detector.update(pose,t,cfg))
    assert any(r.level=="critical" and "fall_transition" in r.reasons for r in results)
    assert detector.phase=="FALL_CONFIRMED" and detector.quality=="partial"


def test_short_occlusion_retains_candidate_but_does_not_count_missing_time():
    cfg=RiskConfig(immobile_seconds=1)
    d=TemporalFallDetector()
    for t in (0,.2,.4): d.update(synthetic_pose(t,True),t,cfg)
    assert d.observed_down==pytest.approx(.4)
    assert "no_pose" in d.update(None,.5,cfg).reasons
    assert d.update(synthetic_pose(.6,True),.6,cfg).level=="suspect"
    assert d.observed_down==pytest.approx(.4)
    for t in (.8,1,1.2): result=d.update(synthetic_pose(t,True),t,cfg)
    assert result.level=="critical"
    d.update(None,2,cfg)
    assert d.phase=="UPRIGHT"
    assert d.update(synthetic_pose(2.1,True),2.1,cfg).level=="suspect"


def test_unsupported_or_out_of_frame_joints_are_not_fabricated():
    cfg=RiskConfig()
    pose=synthetic_pose(0)
    assert features(hidden(pose,(11,12)),0,cfg) is None
    # Opposite unpaired joints must not form an invented torso.
    assert features(hidden(pose,(11,24)),0,cfg) is None
    off=replace(pose,landmarks=tuple(replace(p,y=1.1) if i in (23,24) else p for i,p in enumerate(pose.landmarks)))
    assert features(off,0,cfg) is None


def test_bending_with_feet_below_torso_is_not_confirmed_as_fallen():
    d=TemporalFallDetector(); cfg=RiskConfig()
    for i in range(40):
        pose=synthetic_pose(i*.2)
        points=list(pose.landmarks)
        for joint in (11,12): points[joint]=replace(points[joint],x=.3,y=.55)
        for joint in (23,24): points[joint]=replace(points[joint],x=.5,y=.55)
        for joint in (27,28): points[joint]=replace(points[joint],x=.5,y=.95)
        result=d.update(replace(pose,landmarks=tuple(points)),i*.2,cfg)
        assert result.level!="critical"


def test_static_partial_torso_without_floor_context_is_suspect_not_confirmed():
    d=TemporalFallDetector(); cfg=RiskConfig()
    for i in range(40):
        result=d.update(hidden(synthetic_pose(i*.2,True),(27,28)),i*.2,cfg)
    assert result.level=="suspect" and "floor_context_missing" in result.reasons


def test_bed_is_context_and_not_immunity_to_witnessed_fall():
    cfg=RiskConfig(safe_zones=[[(0,.5),(1,.5),(1,1),(0,1)]])
    static=TemporalFallDetector()
    for i in range(40): assert static.update(synthetic_pose(i*.2,True),i*.2,cfg).level=="ok"
    falling=TemporalFallDetector()
    for i in range(25): result=falling.update(synthetic_pose(i*.2,i>=5),i*.2,cfg)
    assert result.level=="critical"


def test_recovery_uses_lower_angle_and_configuration_change_resets_evidence():
    cfg=RiskConfig(immobile_seconds=.4)
    d=TemporalFallDetector()
    for i in range(4): d.update(synthetic_pose(i*.2,True),i*.2,cfg)
    assert d.phase=="FALL_CONFIRMED"
    pose=synthetic_pose(.7)
    points=list(pose.landmarks)
    import math
    for joint in (11,12):
        points[joint]=replace(points[joint],x=.5-math.sin(math.radians(50))*.3/pose.aspect,y=.55-math.cos(math.radians(50))*.3)
    for joint in (23,24): points[joint]=replace(points[joint],x=.5,y=.55)
    assert d.update(replace(pose,landmarks=tuple(points)),.7,cfg).level=="critical"
    assert d.phase=="FALL_CONFIRMED"
    assert d.update(synthetic_pose(.8),.8,cfg).level=="ok"
    assert d.phase=="UPRIGHT"
    d.update(synthetic_pose(1,True),1,cfg)
    changed=cfg.model_copy(update={"confirm_seconds":3})
    d.update(synthetic_pose(1.2,True),1.2,changed)
    assert d.observed_down==0
