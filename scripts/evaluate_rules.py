"""Evaluación determinista de reglas con poses sintéticas; no mide MediaPipe ni precisión clínica."""
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import RiskConfig
from backend.model_loader import synthetic_pose
from backend.risk import assess


def shifted(pose, dx=0, dy=0):
    return replace(pose, landmarks=tuple(replace(p, x=p.x + dx, y=p.y + dy) for p in pose.landmarks))


def cases(fps):
    times = [i / fps for i in range(8 * fps + 1)]
    standing = [synthetic_pose(t) for t in times]
    lying = [synthetic_pose(t, True) for t in times]
    zone = RiskConfig(safe_zones=[[(0, .5), (1, .5), (1, 1), (0, 1)]])
    invisible = [replace(p, landmarks=tuple(replace(q, visibility=0) for q in p.landmarks)) for p in lying]
    partial = [replace(p, landmarks=p.landmarks[:20]) for p in lying]
    return [
        ("horizontal_immobile", "risk", lying, RiskConfig()),
        ("upright_to_horizontal", "risk", [synthetic_pose(t, t >= 1) for t in times], RiskConfig()),
        ("translated_horizontal", "risk", [shifted(p, dx=.05) for p in lying], RiskConfig()),
        ("standing", "normal", standing, RiskConfig()),
        ("walking", "normal", [shifted(p, dx=.04 * (p.timestamp % 1)) for p in standing], RiskConfig()),
        ("sitting_slowly", "normal", [shifted(p, dy=min(.2, p.timestamp * .05)) for p in standing], RiskConfig()),
        ("lying_in_bed_zone", "normal", lying, zone),
        ("brief_lean_and_recovery", "normal", [synthetic_pose(t, 1 <= t < 2) for t in times], RiskConfig()),
        ("occluded_joints", "unevaluable", invisible, RiskConfig()),
        ("partial_body", "unevaluable", partial, RiskConfig()),
        ("disconnection_gaps", "unevaluable", [synthetic_pose(t, True) for t in (0, 2, 4, 6, 8)], RiskConfig()),
        ("empty_frame", "unevaluable", [], RiskConfig()),
    ]


def evaluate():
    rows = []
    for fps in (5, 30):
        for name, label, poses, config in cases(fps):
            detection = next((p.timestamp for i, p in enumerate(poses)
                              if assess(poses[:i + 1], config).level == "critical"), None)
            onset = 1 if name == "upright_to_horizontal" else 0
            rows.append({"sequence": name, "label": label, "fps": fps,
                         "event_detected": detection is not None,
                         "delay_seconds": None if detection is None else round(detection - onset, 3),
                         "final_reasons": list(assess(poses, config).reasons)})
    counts = {"TP": sum(r["label"] == "risk" and r["event_detected"] for r in rows),
              "FP": sum(r["label"] != "risk" and r["event_detected"] for r in rows),
              "FN": sum(r["label"] == "risk" and not r["event_detected"] for r in rows),
              "unevaluable": sum(r["label"] == "unevaluable" for r in rows)}
    return {"scope": "12 synthetic landmark sequences at 5 and 30 FPS; rules only; not image perception",
            "thresholds": RiskConfig().model_dump(), "counts": counts, "sequences": rows}


if __name__ == "__main__":
    result = evaluate()
    path = ROOT / "reports/rules-evaluation.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"]))
    sys.exit(bool(result["counts"]["FP"] or result["counts"]["FN"]))
