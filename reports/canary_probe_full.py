"""Send the ENTIRE test set (all 1200 rows, no resampling) through the live 90/10
endpoint, one row per request. This avoids the sampling bias found in earlier probes."""
from __future__ import annotations
import csv, sys, time
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import data

FQDN = sys.argv[1]
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/canary_probe_full_log.csv")

df = data.load_raw(Path("data/raw/sensors.csv"))
_, _, test_df = data.split(df, seed=20260101)
fields = ["temp_c","vibration_mm_s","pressure_kpa","hours_since_service","load_pct","ambient_humidity"]

with OUT.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["seq","t_utc","true_label","pred_prob","pred_label","model_version","http_status"])
    for i, (_, row) in enumerate(test_df.iterrows()):
        payload = {k: row[k] for k in fields}
        t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            r = requests.post(f"https://{FQDN}/predict", json=payload, timeout=15)
            body = r.json() if r.status_code == 200 else {}
            prob = body.get("probability")
            mv = body.get("model_version")
            pred = int(prob >= 0.5) if prob is not None else None
            w.writerow([i, t, row["failed_within_7d"], prob, pred, mv, r.status_code])
        except Exception as e:
            w.writerow([i, t, row["failed_within_7d"], None, None, None, f"ERR:{e}"])
        f.flush()
        if i % 100 == 0:
            print(f"{i}/{len(test_df)}", file=sys.stderr)

print(f"Wrote {len(test_df)} rows to {OUT}")
