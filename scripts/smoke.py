"""Smoke test: three known payloads through adapter.invoke()."""
import os
import sys

from cloudlayer.factory import get_adapter
from src import config

PAYLOADS = [
    {"temp_c": 80, "vibration_mm_s": 10, "pressure_kpa": 300, "hours_since_service": 5000, "load_pct": 60, "ambient_humidity": 50},
    {"temp_c": 40, "vibration_mm_s": 2, "pressure_kpa": 250, "hours_since_service": 200, "load_pct": 30, "ambient_humidity": 40},
    {"temp_c": 120, "vibration_mm_s": 45, "pressure_kpa": 500, "hours_since_service": 18000, "load_pct": 95, "ambient_humidity": 80},
]

endpoint = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ENDPOINT", "itcs355-serve")
adapter = get_adapter(config.load())
for i, p in enumerate(PAYLOADS, 1):
    out = adapter.invoke(endpoint, p)
    assert 0.0 <= out["probability"] <= 1.0 and out["model_version"], out
    print(f"payload {i}: {out}")
print("SMOKE PASS")
