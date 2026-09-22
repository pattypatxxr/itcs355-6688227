"""Send labeled test rows in batches to /predict/batch. Each HTTP call is routed to
ONE revision (90/10), so every row in that call shares model_version — more efficient
at accumulating canary-labeled rows than one row per call."""
from __future__ import annotations
import csv, sys, time, random
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import data

FQDN = sys.argv[1]
N_BATCHES = int(sys.argv[2]) if len(sys.argv) > 2 else 100
BATCH_SIZE = int(sys.argv[3]) if len(sys.argv) > 3 else 20
OUT = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("reports/canary_probe_batch_log.csv")

df = data.load_raw(Path("data/raw/sensors.csv"))
_, _, test_df = data.split(df, seed=20260101)
fields = ["temp_c","vibration_mm_s","pressure_kpa","hours_since_service","load_pct","ambient_humidity"]

with OUT.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["t_utc","true_label","pred_prob","pred_label","model_version","http_status"])
    for b in range(N_BATCHES):
        sample = test_df.sample(n=BATCH_SIZE, random_state=random.randint(0, 10**9))
        payload = {"rows": [{k: row[k] for k in fields} for _, row in sample.iterrows()]}
        try:
            r = requests.post(f"https://{FQDN}/predict/batch", json=payload, timeout=20)
            t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if r.status_code == 200:
                body = r.json()
                probs = body["probabilities"]
                mv = body["model_version"]
                for (_, row), p in zip(sample.iterrows(), probs):
                    pred = int(p >= 0.5)
                    w.writerow([t, row["failed_within_7d"], p, pred, mv, 200])
            else:
                w.writerow([t, "", "", "", "", r.status_code])
        except Exception as e:
            w.writerow([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "", "", "", "", f"ERR:{e}"])
        f.flush()
        if b % 10 == 0:
            print(f"batch {b}/{N_BATCHES}", file=sys.stderr)

print(f"Wrote batches to {OUT}")
