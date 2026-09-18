"""Task 3: rank Lab 2 tuning trials by metric and by cost-per-point, then
measure seed variance for the top candidate before anyone writes a
justification for picking it.

Reads reports/lab2-tuning.json (written by src/tune.py) — the only durable
record of trial metrics, since the mlflow backend each job writes to is a
per-job sqlite file destroyed with the job's container.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from pathlib import Path
from typing import Any

from src import config
from cloudlayer.factory import get_adapter
from src.tune import fetch_trial_result

PRIMARY_METRIC = "test_roc_auc"


def load_trials(path: Path) -> list[dict[str, Any]]:
    trials = json.loads(path.read_text())
    completed = [t for t in trials if t.get("status") == "Completed" and PRIMARY_METRIC in t]
    if not completed:
        raise ValueError(f"no completed trials with {PRIMARY_METRIC} found in {path}")
    return completed


def rank_by_metric(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(trials, key=lambda t: t[PRIMARY_METRIC], reverse=True)


def rank_by_cost_efficiency(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def thb_per_auc_point(t: dict[str, Any]) -> float:
        gain = max(t[PRIMARY_METRIC] - 0.5, 1e-6)
        return t["estimated_cost_thb"] / (gain * 100)
    return sorted(trials, key=thb_per_auc_point)


def measure_seed_variance(best: dict[str, Any], extra_seeds: list[int]) -> list[dict[str, Any]]:
    cfg = config.load()
    adapter = get_adapter(cfg)
    image_uri = os.environ["IMAGE_URI"]
    data_uri = os.environ["DATA_URI"]
    resource_group = os.environ["AZURE_RESOURCE_GROUP"]
    workspace = os.environ["AZURE_WORKSPACE_NAME"]

    hp = best["hyperparameters"]
    runs = [{"seed": best["seed"], PRIMARY_METRIC: best[PRIMARY_METRIC]}]

    for seed in extra_seeds:
        args = {**hp, "data-uri": data_uri, "experiment": "itcs355-lab2",
                "run-name": f"variance-check-seed{seed}", "seed": seed}
        print(f"[variance] submitting seed={seed} with hyperparameters={hp}")
        job_id = adapter.submit_training(image_uri, args)
        try:
            outcome = adapter.wait_training(job_id)
            status = getattr(outcome["status"], "value", str(outcome["status"]))
        except RuntimeError as exc:
            print(f"[variance] seed={seed} job failed: {exc}")
            continue
        if status != "Completed":
            print(f"[variance] seed={seed} ended with status={status}, skipping")
            continue
        result = fetch_trial_result(job_id, resource_group, workspace)
        runs.append({"seed": seed, PRIMARY_METRIC: result[PRIMARY_METRIC]})
        print(f"[variance] seed={seed}: {PRIMARY_METRIC}={result[PRIMARY_METRIC]:.4f}")

    return runs


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tuning-file", type=Path, default=Path("reports/lab2-tuning.json"))
    p.add_argument("--out-prefix", type=Path, default=Path("reports/lab2-comparison"))
    p.add_argument("--variance-seeds", type=int, nargs="*", default=[1, 2])
    p.add_argument("--skip-variance-check", action="store_true")
    args = p.parse_args()

    trials = load_trials(args.tuning_file)
    by_metric = rank_by_metric(trials)
    by_cost = rank_by_cost_efficiency(trials)
    best = by_metric[0]
    cheapest_efficient = by_cost[0]

    print(f"\nTop by {PRIMARY_METRIC}: trial {best['trial']} "
          f"({PRIMARY_METRIC}={best[PRIMARY_METRIC]:.4f}, hp={best['hyperparameters']})")
    print(f"Best THB-per-AUC-point: trial {cheapest_efficient['trial']} "
          f"({PRIMARY_METRIC}={cheapest_efficient[PRIMARY_METRIC]:.4f}, "
          f"hp={cheapest_efficient['hyperparameters']})")

    variance_runs: list[dict[str, Any]] = []
    if not args.skip_variance_check:
        variance_runs = measure_seed_variance(best, args.variance_seeds)

    summary = {
        "ranked_by_metric": by_metric,
        "ranked_by_cost_efficiency": by_cost,
        "top_by_metric": best,
        "top_by_cost_efficiency": cheapest_efficient,
        "seed_variance_check": {
            "hyperparameters": best["hyperparameters"],
            "runs": variance_runs,
            "stdev": statistics.pstdev([r[PRIMARY_METRIC] for r in variance_runs])
                     if len(variance_runs) > 1 else None,
        },
    }

    args.out_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.out_prefix.with_suffix(".json").write_text(json.dumps(summary, indent=2))

    with args.out_prefix.with_suffix(".csv").open("w") as f:
        f.write("trial,job_id,n_estimators,max_depth,min_samples_leaf,seed,"
                "val_roc_auc,test_roc_auc,wall_clock_seconds,estimated_cost_thb\n")
        for t in by_metric:
            hp = t["hyperparameters"]
            f.write(f"{t['trial']},{t['job_id']},{hp['n-estimators']},{hp['max-depth']},"
                    f"{hp['min-samples-leaf']},{t['seed']},{t['val_roc_auc']:.4f},"
                    f"{t['test_roc_auc']:.4f},{t['wall_clock_seconds']:.1f},"
                    f"{t['estimated_cost_thb']:.4f}\n")

    print(f"\nWrote {args.out_prefix}.json and {args.out_prefix}.csv")
    if variance_runs:
        vals = [r[PRIMARY_METRIC] for r in variance_runs]
        print(f"Seed variance for top candidate: {[f'{v:.4f}' for v in vals]} "
              f"(stdev={statistics.pstdev(vals):.4f})")


if __name__ == "__main__":
    main()
