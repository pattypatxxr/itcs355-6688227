"""Lab 4 — scheduled drift check. Runs as a cron job against the live service.

Pulls the service's rolling window of recent inputs, scores PSI per feature against the
training reference, emits every score as a metric, and posts to a chat webhook when a
feature reaches the threshold. The threshold and its evidence live in monitoring/drift.py.

    python -m monitoring.drift_job --url https://<fqdn>

Exit codes: 0 = ran (ok, alerted, or skipped for lack of data); 1 = ran, but a metric or the
alert failed to send; 2 = misconfigured, or the service window could not be fetched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from monitoring.drift import PSI_MODERATE, compare


def run(window: dict, reference: pd.DataFrame, features: list[str], threshold: float,
        min_rows: int, emit: Callable[[str, float], None],
        alert: Callable[[str], None]) -> dict:
    """Score one window. All I/O is injected so the decision logic can be tested alone."""
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = int(window.get("n", 0))
    present = window.get("features", {})
    emit("drift.window_rows", float(n))

    missing = [f for f in features if f not in present]
    if n and missing:  # first branch of the post-mortem flowchart: the schema moved
        alert(f"ITCS355 drift job {stamp}: SCHEMA CHANGE. The service window has no values for "
              + ", ".join(missing) + ". Do not retrain; find which producer changed.")
        return {"status": "schema_changed", "rows": n, "missing": missing}

    # PSI noise was measured at 500 rows; a smaller window is noisier than the threshold assumes.
    if n < min_rows:
        return {"status": "skipped", "rows": n}

    current = pd.DataFrame({f: present[f] for f in features})
    results = compare(reference, current, features)  # sorted by PSI, highest first
    for r in results:
        emit(f"drift.psi.{r.feature}", r.psi)
    emit("drift.psi.max", results[0].psi)

    breached = [r for r in results if r.psi >= threshold]
    if breached:
        lines = [f"ITCS355 drift ALERT {stamp}",
                 f"{len(breached)} of {len(features)} features at or above PSI {threshold} "
                 f"(window: {n} rows)"]
        lines += [f"  {r.feature}: PSI {r.psi:.3f}, mean {r.ref_mean:.2f} -> {r.cur_mean:.2f}"
                  for r in breached]
        lines.append("Before retraining: did the schema or null rate change? A broken upstream "
                     "producer means do not retrain; fix the producer first.")
        alert("\n".join(lines))
    return {"status": "alert" if breached else "ok", "rows": n, "max_psi": results[0].psi,
            "breached": [r.feature for r in breached]}


def fetch_window(url: str, token: str, timeout: float) -> dict:
    request = urllib.request.Request(url.rstrip("/") + "/internal/window",
                                     headers={"x-drift-token": token})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def post_alert(webhook: str, text: str) -> None:
    text = text[:1900]  # Discord rejects messages over 2000 characters
    request = urllib.request.Request(
        webhook, data=json.dumps({"content": text, "text": text}).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "itcs355-drift-job/1.0"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src import config, data  # importing config loads cloud.env into the environment
    from cloudlayer.factory import get_adapter

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=os.environ.get("TARGET_URL"), help="service base URL")
    ap.add_argument("--reference", type=Path,
                    default=Path(os.environ.get("REFERENCE_CSV", "data/raw/sensors.csv")))
    ap.add_argument("--threshold", type=float, default=PSI_MODERATE)
    ap.add_argument("--min-rows", type=int, default=500)
    ap.add_argument("--timeout", type=float, default=150.0,
                    help="seconds; the first call may wait out a scale-to-zero cold start")
    args = ap.parse_args()
    if not args.url:
        ap.error("--url or TARGET_URL is required")

    token = os.environ.get("DRIFT_TOKEN", "")
    webhook = os.environ.get("ALERT_WEBHOOK_URL", "")
    if not token or not webhook:  # a drift job that cannot alert is broken, so say so loudly
        print("DRIFT_TOKEN and ALERT_WEBHOOK_URL must both be set", file=sys.stderr)
        return 2

    try:
        window = fetch_window(args.url, token, args.timeout)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"could not fetch the window: {exc}", file=sys.stderr)
        return 2

    adapter = get_adapter(config.load(strict=False))
    errors: list[str] = []

    def emit(name: str, value: float) -> None:
        try:
            adapter.emit_metric(name, float(value))
        except Exception as exc:  # keep going: the alert matters more than one metric
            errors.append(f"emit {name}: {exc}")

    def alert(text: str) -> None:
        try:
            post_alert(webhook, text)
        except Exception as exc:
            errors.append(f"alert: {exc}")

    reference = pd.read_csv(args.reference)
    outcome = run(window, reference, list(data.FEATURES), args.threshold, args.min_rows, emit, alert)
    print(json.dumps(outcome))
    for line in errors:
        print("ERROR", line, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
