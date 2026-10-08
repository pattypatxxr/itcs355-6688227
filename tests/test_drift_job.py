"""Lab 4 — the drift job's decisions: skip, stay quiet, alert, flag a schema change."""
from __future__ import annotations

import pandas as pd
import pytest

from monitoring.drift import PSI_MODERATE
from monitoring.drift_job import run
from src import config, data

RAW = config.REPO_ROOT / "data" / "raw" / "sensors.csv"


@pytest.fixture(scope="module")
def reference():
    if not RAW.exists():
        pytest.skip("run `make data` first")
    return pd.read_csv(RAW)


def _window(reference, shift=0.0, n=500, seed=3):
    rows = reference[data.FEATURES].sample(n=n, random_state=seed)
    features = {f: rows[f].tolist() for f in data.FEATURES}
    features["temp_c"] = [v + shift for v in features["temp_c"]]
    return {"n": n, "features": features}


def _run(window, reference, min_rows=500):
    emitted, alerts = {}, []
    outcome = run(window, reference, list(data.FEATURES), PSI_MODERATE, min_rows,
                  lambda name, value: emitted.__setitem__(name, value), alerts.append)
    return outcome, emitted, alerts


def test_skips_a_window_that_is_too_small_to_trust(reference):
    outcome, emitted, alerts = _run(_window(reference, n=40), reference)
    assert outcome["status"] == "skipped"
    assert alerts == []
    assert emitted == {"drift.window_rows": 40.0}


def test_stays_quiet_on_unshifted_traffic_and_still_reports_scores(reference):
    outcome, emitted, alerts = _run(_window(reference), reference)
    assert outcome["status"] == "ok" and alerts == []
    assert emitted["drift.psi.max"] < PSI_MODERATE
    assert "drift.psi.temp_c" in emitted


def test_alerts_when_temp_c_shifts_by_six_degrees(reference):
    outcome, emitted, alerts = _run(_window(reference, shift=6.0), reference)
    assert outcome["status"] == "alert" and outcome["breached"] == ["temp_c"]
    assert len(alerts) == 1 and "temp_c" in alerts[0]
    assert emitted["drift.psi.temp_c"] >= PSI_MODERATE


def test_a_missing_feature_is_a_schema_alert_not_a_drift_score(reference):
    window = _window(reference)
    del window["features"]["vibration_mm_s"]
    outcome, emitted, alerts = _run(window, reference)
    assert outcome["status"] == "schema_changed"
    assert "vibration_mm_s" in alerts[0] and "Do not retrain" in alerts[0]
    assert not any(name.startswith("drift.psi") for name in emitted)
