"""Send realistic traffic to a /predict endpoint (Lab 4 dashboard and drift exercises).

    python scripts/send_traffic.py --url https://<fqdn>/predict --rate 3 --duration 600
    python scripts/send_traffic.py --url ... --csv data/current.csv   # replay shifted data

A share of requests is deliberately malformed so the 4xx panel has something to show.
Status 0 in the summary means the request never got an HTTP response (timeout, DNS).
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

# Same six inputs as src.data.FEATURES, repeated here so this script has no repo imports.
FEATURES = ["temp_c", "vibration_mm_s", "pressure_kpa",
            "hours_since_service", "load_pct", "ambient_humidity"]


def post(url: str, body: dict, timeout: float) -> int:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError):
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True, help="https://<fqdn>/predict")
    ap.add_argument("--csv", type=Path, default=Path("data/raw/sensors.csv"))
    ap.add_argument("--rate", type=float, default=3.0, help="requests per second")
    ap.add_argument("--duration", type=float, default=300.0, help="seconds")
    ap.add_argument("--bad-fraction", type=float, default=0.05,
                    help="share of malformed requests, answered with 4xx")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    with args.csv.open(newline="") as handle:
        rows = [{k: float(r[k]) for k in FEATURES} for r in csv.DictReader(handle)]

    rng = random.Random(args.seed)
    counts: dict[int, int] = {}
    interval = 1.0 / args.rate
    end = time.monotonic() + args.duration
    last_report = time.monotonic()
    print(f"sending {args.rate}/s for {args.duration:.0f}s to {args.url}  "
          f"({len(rows)} rows from {args.csv})")
    while time.monotonic() < end:
        started = time.monotonic()
        body = {"temp_c": "not-a-number"} if rng.random() < args.bad_fraction else rng.choice(rows)
        status = post(args.url, body, timeout=120.0)  # the first call may wait out a cold start
        counts[status] = counts.get(status, 0) + 1
        if time.monotonic() - last_report >= 30:
            print("  so far:", dict(sorted(counts.items())))
            last_report = time.monotonic()
        time.sleep(max(0.0, interval - (time.monotonic() - started)))

    print("done:", dict(sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
