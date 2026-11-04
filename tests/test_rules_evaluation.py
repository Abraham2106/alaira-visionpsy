from scripts.evaluate_rules import evaluate
import hashlib


def test_labeled_rules_suite_is_equivalent_at_5_and_30_fps():
    result = evaluate()
    assert result["counts"] == {"TP": 6, "FP": 0, "FN": 0, "unevaluable": 8}
    rows = result["sequences"]
    for slow, fast in zip(rows[:12], rows[12:]):
        assert slow["sequence"] == fast["sequence"]
        assert slow["event_detected"] == fast["event_detected"]
        if slow["event_detected"]:
            assert abs(slow["delay_seconds"] - fast["delay_seconds"]) <= .2


def test_evaluation_uses_configured_thresholds_without_hiding_failures(tmp_path):
    config=tmp_path/"config.yaml"
    config.write_text("risk:\n  immobile_seconds: 9\n",encoding="utf-8")
    result=evaluate(config)
    assert result["configuration_sha256"]==hashlib.sha256(config.read_bytes()).hexdigest()
    assert result["thresholds"]["immobile_seconds"]==9
    assert result["counts"]["TP"]==0 and result["counts"]["FN"]==6
