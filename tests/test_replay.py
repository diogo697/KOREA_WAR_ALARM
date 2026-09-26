from korea_war_alarm.replay import replay


def test_synthetic_replay():
    result = replay("tests/fixtures/synthetic_attack.json")
    assert result["passed"]
    assert result["high_alert_time"] == "2026-01-01T00:00:12+00:00"
    assert result["critical_alert_time"] == "2026-01-01T00:00:35+00:00"


def test_historical_sensor_does_not_mean_war():
    result = replay("tests/fixtures/historical_dprk_2017.json")
    assert result["passed"]
    assert result["false_positive_count"] == 0
    assert result["critical_alert_time"] is None


def test_raw_sources_nonwar_replay():
    result = replay("tests/fixtures/source_v2_nonwar.json")
    assert result["passed"]
    assert result["false_positive_count"] == 0
    assert result["notification_count"] == 0
    assert result["transitions"][0]["level"] == "WATCH"
    assert "not measured" in result["timing_basis"]
