"""Lab 2 — register the chosen model with full lineage, then promote it.

    python scripts/register_model.py --trial-index 4 --image-digest <repo@sha256:...>

Reads the chosen trial from reports/lab2-tuning.json, pulls git_commit and
data_fingerprint from the matching MLflow run (train.py already logs both as tags
on every run), and registers through the adapter — never straight through the
MLflow client, so this stays portable across providers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mlflow

from src import config
from cloudlayer.factory import get_adapter

TUNING_JSON = Path(__file__).resolve().parents[1] / "reports" / "lab2-tuning.json"
DVC_FILE = Path(__file__).resolve().parents[1] / "data" / "raw.dvc"


def _dvc_hash() -> str:
    import re
    text = DVC_FILE.read_text()
    m = re.search(r"md5:\s*([0-9a-f]+)", text)
    if not m:
        raise RuntimeError(f"Could not find md5 hash in {DVC_FILE}")
    return m.group(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial-index", type=int, required=True,
                     help="index into reports/lab2-tuning.json for the chosen trial")
    ap.add_argument("--image-digest", required=True,
                     help="repo@sha256:... digest of the image used to train this trial")
    ap.add_argument("--stage", default="Development",
                     help="Development | Production | Archived")
    args = ap.parse_args()

    cfg = config.load()
    trials = json.loads(TUNING_JSON.read_text())
    trial = trials[args.trial_index]
    job_id = trial["job_id"]
    mlflow_run_id = trial["mlflow_run_id"]

    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    run = mlflow.MlflowClient().get_run(mlflow_run_id)
    git_commit = run.data.tags.get("git_commit")
    if not git_commit:
        raise RuntimeError(f"Run {job_id} has no git_commit tag — check job_id/run_id mapping")

    tags = {
        "git_commit": git_commit,
        "data_version": _dvc_hash(),
        "mlflow_run_id": mlflow_run_id,
        "training_job_id": job_id,
        "image_digest": args.image_digest,
        "seed": str(trial["seed"]),
        "metric_val": str(trial["val_roc_auc"]),
        "metric_test": str(trial["test_roc_auc"]),
    }
    print("Registering with lineage tags:")
    print(json.dumps(tags, indent=2))

    adapter = get_adapter(cfg)
    model_uri = f"azureml://jobs/{job_id}/outputs/model"
    version = adapter.register_model(model_uri, cfg.model_registry_name, tags=tags)
    print(f"\nRegistered: {version}")

    # --- promote ---
    ml_client = adapter._ml_client()
    name, ver = version.split(":")
    promoted = ml_client.models.get(name=name, version=ver)
    promoted.stage = args.stage
    ml_client.models.create_or_update(promoted)
    print(f"Promoted {version} to stage={args.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
