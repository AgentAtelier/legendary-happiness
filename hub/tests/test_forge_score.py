"""Unit tests for forge_score — unified scoring, verdict bands, ETA."""

from forge_score import score_to_verdict, normalize_result, eta_from_durations


class TestVerdict:
    def test_pass_at_90(self):
        assert score_to_verdict(90) == "pass"
        assert score_to_verdict(100) == "pass"

    def test_partial_band(self):
        assert score_to_verdict(60) == "partial"
        assert score_to_verdict(89) == "partial"

    def test_fail_below_60(self):
        assert score_to_verdict(59) == "fail"
        assert score_to_verdict(0) == "fail"

    def test_custom_thresholds(self):
        assert score_to_verdict(80, pass_at=80, partial_at=50) == "pass"


class TestNormalize:
    def test_health_passfail_maps_to_100_0(self):
        raw = {"checks": [{"name": "llama", "passed": True},
                          {"name": "devforge", "passed": True},
                          {"name": "godot", "passed": False}]}
        card = normalize_result("health", raw, target="current", label="quick")
        assert card["suite"] == "health"
        assert card["score"] == 67  # 2/3 rounded
        assert card["verdict"] == "partial"  # 67 lands in the 60-89 partial band
        assert {"label": "godot", "value": "fail", "good": False} in card["metrics"]

    def test_gauntlet_coverage_is_score(self):
        raw = {"coverage": 83, "metrics": {"depth": "1/4", "scripts": 4,
                                           "nodes": "3/25", "overlap": 0}}
        card = normalize_result("gauntlet", raw, target="current", label="G7")
        assert card["score"] == 83
        assert card["verdict"] == "partial"
        labels = {m["label"]: m for m in card["metrics"]}
        assert labels["scripts"]["good"] is True
        assert labels["nodes"]["good"] is False
        assert labels["overlap"]["good"] is True

    def test_scenarios_coverage_is_score(self):
        raw = {"coverage": 95, "metrics": {"geometry": "9/10", "tools": "ok"}}
        card = normalize_result("scenarios", raw, target="current", label="all")
        assert card["score"] == 95
        assert card["verdict"] == "pass"


class TestEta:
    def test_median_of_recent(self):
        assert eta_from_durations([100, 120, 110], recent=5) == 110

    def test_caps_to_recent(self):
        assert eta_from_durations([10, 10, 10, 200, 300], recent=2) == 250

    def test_too_few_returns_none(self):
        assert eta_from_durations([90], recent=5) is None
        assert eta_from_durations([], recent=5) is None
