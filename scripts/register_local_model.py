"""Lab 3 — register the deliberately degraded canary model (trained locally, not via a managed job).

Lineage is honest: there is no managed training job or image digest, so those tags say so.
Reuses the adapter; never promotes."""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config
from cloudlayer.factory import get_adapter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--metrics", type=Path, required=True)
    a = ap.parse_args()

    m = json.loads(a.metrics.read_text())
    md5 = re.search(r"md5:\s*([0-9a-f]+)", (ROOT / "data" / "raw.dvc").read_text()).group(1)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tags = {
        "git_commit": commit,
        "data_version": md5,
        "mlflow_run_id": m["mlflow_run_id"],
        "training_job_id": "local-run-no-managed-job",
        "image_digest": "none-local-train",
        "seed": str(m["seed"]),
        "metric_val": str(m["val_roc_auc"]),
        "metric_test": str(m["test_roc_auc"]),
        "purpose": "lab3-canary-degraded",
        "do_not_promote": "true",
    }
    print(json.dumps(tags, indent=2))
    cfg = config.load()
    version = get_adapter(cfg).register_model(str(a.model_dir.resolve()), cfg.model_registry_name, tags=tags)
    print("Registered:", version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
