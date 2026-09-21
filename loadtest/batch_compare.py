"""Lab 3 - batch vs single, and payload-size sweep. Concurrency 1, keep-alive.
Standalone (does NOT import locustfile: locust's gevent monkey-patching breaks requests/ssl).
Usage: python loadtest/batch_compare.py https://<endpoint>"""
import random, sys, time, statistics as st
import requests


def sample_payload() -> dict:
    # keep identical to loadtest/locustfile.py
    return {
        "temp_c": round(random.uniform(60, 95), 3),
        "vibration_mm_s": round(random.uniform(1.0, 8.0), 3),
        "pressure_kpa": round(random.uniform(280, 350), 3),
        "hours_since_service": round(random.uniform(0, 9000), 3),
        "load_pct": round(random.uniform(20, 100), 3),
        "ambient_humidity": round(random.uniform(30, 85), 3),
    }


base = sys.argv[1].rstrip("/")
s = requests.Session()
s.post(f"{base}/predict", json=sample_payload())  # warm connection


def timed(fn):
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


print("| rows | N single calls (ms) | 1 batch call (ms) | speedup | batch ms/row |")
print("|---|---|---|---|---|")
for n in (1, 10, 50, 100):
    rows = [sample_payload() for _ in range(n)]
    single = [timed(lambda: [s.post(f"{base}/predict", json=r) for r in rows]) for _ in range(5)]
    batch = [timed(lambda: s.post(f"{base}/predict/batch", json={"rows": rows})) for _ in range(10)]
    ms, mb = st.median(single), st.median(batch)
    print(f"| {n} | {ms:.0f} | {mb:.0f} | {ms/mb:.1f}x | {mb/n:.1f} |")
