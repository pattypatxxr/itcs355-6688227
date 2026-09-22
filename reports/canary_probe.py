"""Send labeled test rows to the live endpoint, split 90/10 by the app's own traffic
weights, and log every response with its true label and which model_version answered.
Used to detect the canary's quality degradation from metrics alone (Task 4)."""
from __future__ import annotations
import csv, json, sys, time
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import data, seeds

FQDN = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("reports/canary_probe_log.csv")

seeds.set_all(20260101)
df = data.load_raw(Path("data/raw/sensors.csv"))
_, _, test_df = data.split(df, seed=20260101)
rows = test_df.sample(n=min(N, len(test_df)), random_state=20260101).to_dict("records")

fields = ["temp_c","vibration_mm_s","pressure_kpa","hours_since_service","load_pct","ambient_humidity"]

with OUT.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["t_utc","true_label","pred_prob","pred_label","model_version","http_status","latency_s"])
    for i, row in enumerate(rows):
        payload = {k: row[k] for k in fields}
        t0 = time.time()
        try:
            r = requests.post(f"https://{FQDN}/predict", json=payload, timeout=15)
            lat = time.time() - t0
            body = r.json() if r.status_code == 200 else {}
            prob = body.get("probability")
            mv = body.get("model_version")
            pred = int(prob >= 0.5) if prob is not None else None
            w.writerow([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), row["failed_within_7d"],
                        prob, pred, mv, r.status_code, f"{lat:.3f}"])
        except Exception as e:
            w.writerow([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), row["failed_within_7d"],
                        None, None, None, f"ERR:{e}", ""])
        f.flush()
        if i % 20 == 0:
            print(f"{i}/{len(rows)}", file=sys.stderr)

print(f"Wrote {len(rows)} rows to {OUT}")
