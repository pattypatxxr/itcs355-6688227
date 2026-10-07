"""Lab 3/4 — service contract tests."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src import config, data, seeds  # noqa: E402

RAW = config.REPO_ROOT / "data" / "raw" / "sensors.csv"
VALID = {
    "temp_c": 78.4, "vibration_mm_s": 3.1, "pressure_kpa": 315.2,
    "hours_since_service": 4200.0, "load_pct": 68.0, "ambient_humidity": 55.0,
}


@pytest.fixture(scope="module")
def client():
    if not RAW.exists():
        pytest.skip("run `make data` first")
    model_path = config.REPO_ROOT / "reports" / "model.joblib"
    if not model_path.exists():
        import joblib
        from sklearn.ensemble import RandomForestClassifier

        seed = seeds.set_all()
        df = data.load_raw(RAW)
        train_df, _, _ = data.split(df, seed=seed)
        model = RandomForestClassifier(n_estimators=60, max_depth=8, random_state=seed)
        model.fit(train_df[data.FEATURES], train_df[data.TARGET])
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, model_path)

    os.environ["MODEL_PATH"] = str(model_path)
    os.environ["MODEL_VERSION"] = "test-1"
    os.environ.pop("MODEL_REGISTRY_NAME", None)

    from service.app import app
    with TestClient(app) as c:
        yield c


def test_health_and_ready_are_different(client):
    """Liveness passes whenever the process is up. Readiness only when it can score."""
    assert client.get("/health").json()["status"] == "alive"
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_predict_returns_probability_and_version(client):
    r = client.post("/predict", json=VALID)
    assert r.status_code == 200
    body = r.json()
    assert 0.0 <= body["probability"] <= 1.0
    assert body["model_version"] == "test-1"
    assert r.headers["x-model-version"] == "test-1"
    assert r.headers["x-request-id"]


def test_out_of_range_input_is_rejected(client):
    bad = {**VALID, "load_pct": 250.0}
    assert client.post("/predict", json=bad).status_code == 422


def test_unknown_field_is_rejected(client):
    """extra='forbid'. A silently ignored field is how a caller ends up sending a feature
    you never read while believing it matters."""
    assert client.post("/predict", json={**VALID, "surprise": 1}).status_code == 422


def test_missing_field_is_rejected(client):
    incomplete = {k: v for k, v in VALID.items() if k != "temp_c"}
    assert client.post("/predict", json=incomplete).status_code == 422


def test_batch_matches_singles(client):
    rows = [VALID, {**VALID, "temp_c": 92.0}]
    batch = client.post("/predict/batch", json={"rows": rows}).json()["probabilities"]
    singles = [client.post("/predict", json=r).json()["probability"] for r in rows]
    assert batch == pytest.approx(singles, abs=1e-9)


def test_batch_size_limit_enforced(client):
    r = client.post("/predict/batch", json={"rows": [VALID] * 101})
    assert r.status_code == 422


def test_metrics_exposes_the_series_the_dashboard_queries(client):
    """dashboard.json queries these names. If one is renamed the dashboard goes blank
    silently, which is the 'metrics emitted to a different namespace' failure in the lab."""
    assert client.post("/predict", json=VALID).status_code == 200
    assert client.post("/predict", json={"temp_c": "not-a-number"}).status_code == 422

    text = client.get("/metrics").text
    assert 'http_requests_total{path="/predict",status_class="2xx"}' in text
    assert 'http_requests_total{path="/predict",status_class="4xx"}' in text
    assert 'request_latency_ms_bucket{le="+Inf"}' in text
    assert 'model_version_info{version="test-1"} 1' in text
    assert 'feature_rolling_mean{feature="temp_c"}' in text


def test_probes_and_scrapes_are_not_counted_as_traffic(client):
    client.get("/health")
    client.get("/ready")
    client.get("/metrics")
    text = client.get("/metrics").text
    assert 'path="/health"' not in text
    assert 'path="/metrics"' not in text


def test_serving_image_runs_one_worker():
    """metrics.py keeps counters in process memory. With N uvicorn workers a scrape lands on
    a random worker and the counters jump between N independent values, so rate() is wrong.
    Move metrics to prometheus_client multiprocess mode before raising this."""
    dockerfile = (config.REPO_ROOT / "service" / "Dockerfile.serve").read_text()
    assert '"--workers", "1"' in dockerfile
