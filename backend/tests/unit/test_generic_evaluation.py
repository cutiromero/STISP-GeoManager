"""Scoring of geology checks against labelled simulated inputs."""

import json

from apps.agent.generic_evaluation import metrics, reported, sweep


def issue(element, feature, rule, status="review", confidence=None):
    measurements = {} if confidence is None else {"simulation_confidence": confidence}
    return {
        "element": element,
        "feature_id": feature,
        "rule_id": rule,
        "status": status,
        "measurements_json": json.dumps(measurements),
    }


def test_relation_scores_count_hits_misses_and_false_alarms():
    lith = {"F00001": "L-01", "F00002": "L-02", "F00003": "benign", "F00004": ""}
    faults = {"S00001": "valley", "S00002": "plausible", "S00003": ""}
    issues = [
        issue("lithology", "F00001", "L-01"),
        issue("lithology", "F00004", "L-02"),
        issue("lithology", "F00003", "L-01", status="exception"),
        issue("structure", "S00001", "S-01"),
    ]
    _, relations = metrics(reported(issues), lith, faults)
    contact = next(r for r in relations if r["relation"] == "地层接触")
    assert (contact["tp"], contact["fp"], contact["fn"]) == (1, 1, 1)
    structure = next(r for r in relations if r["relation"] == "构造切割")
    # A shape-normal fake line is a real conflict no rule catches: it is a miss.
    assert (structure["tp"], structure["fn"], structure["recall"]) == (1, 1, 0.5)


def test_threshold_moves_confident_hits_to_exceptions():
    lith = {"F00001": "L-01", "F00002": "", "F00003": "L-04"}
    issues = [
        issue("lithology", "F00001", "L-01", confidence=0.55),
        issue("lithology", "F00002", "L-01", confidence=0.95),
        issue("lithology", "F00003", "L-04", confidence=0.65),
    ]
    assert len(reported(issues, threshold=0.9)) == 2
    rows, chosen = sweep(issues, lith, {})
    assert chosen["meets_target"] is True
    assert 0.66 <= chosen["threshold"] <= 0.95
