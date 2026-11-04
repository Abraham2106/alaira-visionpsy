from scripts.evaluate_rules import evaluate


def test_labeled_rules_suite_is_equivalent_at_5_and_30_fps():
    result = evaluate()
    assert result["counts"] == {"TP": 6, "FP": 0, "FN": 0, "unevaluable": 8}
    rows = result["sequences"]
    for slow, fast in zip(rows[:12], rows[12:]):
        assert slow["sequence"] == fast["sequence"]
        assert slow["event_detected"] == fast["event_detected"]
        if slow["event_detected"]:
            assert abs(slow["delay_seconds"] - fast["delay_seconds"]) <= .2
