"""Prometheus text-format metrics for the prediction service.

Hand-rolled on purpose: no new dependency, so the hash-pinned requirements and the serving
image pins do not change. Series names match monitoring/dashboard.json.
"""
from __future__ import annotations

import math
import threading
from collections import deque

LATENCY_BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)
WINDOW = 500  # rolling window: the last N rows this replica has scored
UNMEASURED_PATHS = {"/metrics", "/health", "/ready"}  # probes and scrapes are not traffic

_lock = threading.Lock()
_requests: dict[tuple[str, str], int] = {}
_buckets = [0] * (len(LATENCY_BUCKETS_MS) + 1)  # per-bucket counts; last slot is +Inf
_latency = {"sum": 0.0, "count": 0}
_window: dict[str, deque] = {}


def record_request(path: str, status: int, latency_ms: float) -> None:
    if path in UNMEASURED_PATHS:
        return
    key = (path, f"{status // 100}xx")
    slot = next((i for i, b in enumerate(LATENCY_BUCKETS_MS) if latency_ms <= b),
                len(LATENCY_BUCKETS_MS))
    with _lock:
        _requests[key] = _requests.get(key, 0) + 1
        _buckets[slot] += 1
        _latency["sum"] += latency_ms
        _latency["count"] += 1


def observe_features(rows: list[dict]) -> None:
    with _lock:
        for row in rows:
            for name, value in row.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    _window.setdefault(name, deque(maxlen=WINDOW)).append(float(value))


def _escape(value) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def render(model_version) -> str:
    with _lock:
        requests = dict(_requests)
        buckets = list(_buckets)
        lat_sum, lat_count = _latency["sum"], _latency["count"]
        window = {name: list(vals) for name, vals in _window.items()}

    out = ["# HELP http_requests_total Requests by path and status class.",
           "# TYPE http_requests_total counter"]
    for (path, status_class), n in sorted(requests.items()):
        out.append(f'http_requests_total{{path="{path}",status_class="{status_class}"}} {n}')

    out += ["# HELP request_latency_ms Request latency in milliseconds.",
            "# TYPE request_latency_ms histogram"]
    cumulative = 0
    for bound, count in zip(LATENCY_BUCKETS_MS, buckets):
        cumulative += count
        out.append(f'request_latency_ms_bucket{{le="{bound}"}} {cumulative}')
    cumulative += buckets[-1]
    out.append(f'request_latency_ms_bucket{{le="+Inf"}} {cumulative}')
    out.append(f"request_latency_ms_sum {lat_sum:.3f}")
    out.append(f"request_latency_ms_count {lat_count}")

    out += ["# HELP model_version_info Model version currently served.",
            "# TYPE model_version_info gauge",
            f'model_version_info{{version="{_escape(model_version)}"}} 1']

    out += ["# HELP feature_rolling_mean Mean of each input feature over the last WINDOW rows.",
            "# TYPE feature_rolling_mean gauge",
            "# HELP feature_rolling_std Std of each input feature over the last WINDOW rows.",
            "# TYPE feature_rolling_std gauge",
            "# HELP feature_window_size Rows currently in the rolling window.",
            "# TYPE feature_window_size gauge"]
    for name in sorted(window):
        vals = window[name]
        n = len(vals)
        mean = sum(vals) / n
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)
        out.append(f'feature_rolling_mean{{feature="{name}"}} {mean:.4f}')
        out.append(f'feature_rolling_std{{feature="{name}"}} {std:.4f}')
        out.append(f'feature_window_size{{feature="{name}"}} {n}')
    return "\n".join(out) + "\n"
