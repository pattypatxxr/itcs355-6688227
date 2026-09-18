"""One-off: fix status + fetch metrics for trials that already ran, so we
don't have to re-spend budget re-running training that already succeeded."""
import json
import os
from pathlib import Path

from src.tune import fetch_trial_result

RESOURCE_GROUP = os.environ["AZURE_RESOURCE_GROUP"]
WORKSPACE = os.environ["AZURE_WORKSPACE_NAME"]
PATH = Path("reports/lab2-tuning.json")

records = json.loads(PATH.read_text())
for r in records:
    job_id = r["job_id"]
    print(f"[trial {r['trial']}] checking {job_id} ...")
    try:
        metrics = fetch_trial_result(job_id, RESOURCE_GROUP, WORKSPACE)
        r.update(metrics)
        r["status"] = "Completed"
        r.pop("error", None)
        print(f"  OK: val_roc_auc={metrics.get('val_roc_auc')}")
    except Exception as exc:
        print(f"  FAILED to fetch: {exc}")
        r["metrics_fetch_error"] = str(exc)

PATH.write_text(json.dumps(records, indent=2))
completed = [r for r in records if r["status"] == "Completed"]
print(f"\nDone. {len(completed)}/{len(records)} trials now have status=Completed with metrics.")
