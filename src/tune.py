"""Budgeted hyperparameter study for Lab 2, Task 2.

Runs src/train.py inside the same container image used for `make train-remote`,
across a grid of hyperparameters, tracking wall-clock time and an *estimated*
cost per trial (from Azure's public retail-price API), stopping at whichever
comes first: --trials trials, or --budget-thb THB spent.

Every run logs: all hyperparameters, the seed, validation AND test metrics
separately, wall-clock seconds, the instance type, and the estimated cost.
A metric that cannot be traced to a trial record is not evidence of anything.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

from src import config
from cloudlayer.factory import get_adapter

INSTANCE_TYPE = "Standard_DS3_v2"
REGION = "japanwest"
FALLBACK_USD_PER_HOUR = 0.10  # only used if the live price lookup fails
USD_TO_THB = 36.0             # approximate FX; documented assumption, not live


def get_hourly_price_thb() -> float:
    """Live Linux pay-as-you-go price for INSTANCE_TYPE in REGION.

    Uses Azure's public Retail Prices API (no auth needed). Falls back to a
    conservative hardcoded estimate if the call fails; the fallback is always
    printed so it's obvious in the log which one was used.
    """
    try:
        url = "https://prices.azure.com/api/retail/prices"
        filter_q = (
            f"armRegionName eq '{REGION}' and armSkuName eq '{INSTANCE_TYPE}' "
            "and priceType eq 'Consumption' and contains(productName, 'Linux')"
        )
        resp = requests.get(url, params={"$filter": filter_q}, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("Items", [])
        if not items:
            raise ValueError("no matching SKU returned by retail price API")
        usd_per_hour = min(item["retailPrice"] for item in items)
        return usd_per_hour * USD_TO_THB
    except Exception as exc:  # noqa: BLE001 - a price-lookup failure must not kill the study
        print(f"WARN: could not fetch live price ({exc}); using fallback estimate")
        return FALLBACK_USD_PER_HOUR * USD_TO_THB


def hyperparameter_grid() -> list[dict[str, int]]:
    """>=3 hyperparameters, >=12 combinations (3*3*2 = 18 here)."""
    n_estimators = [100, 200, 400]
    max_depth = [4, 8, 12]
    min_samples_leaf = [1, 5]
    return [
        {"n-estimators": n, "max-depth": d, "min-samples-leaf": m}
        for n, d, m in itertools.product(n_estimators, max_depth, min_samples_leaf)
    ]


def fetch_trial_result(job_id: str, resource_group: str, workspace: str) -> dict[str, Any]:
    """Pull the trailing JSON that src/train.py prints to stdout.

    Uses the Azure CLI (not the Python SDK) to download job logs: the SDK's
    log-download path hits the same SAS-token bug fixed in wait_training().
    """
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["az", "ml", "job", "download", "-n", job_id,
             "-g", resource_group, "-w", workspace, "--download-path", tmp],
            check=True, capture_output=True, text=True,
        )
        candidates = list(Path(tmp).rglob("std_log.txt"))
        if not candidates:
            raise FileNotFoundError(f"no std_log.txt found under {tmp}")
        text = candidates[0].read_text()
        last_brace = text.rfind("\n{")
        json_blob = text[last_brace:] if last_brace != -1 else text
        return json.loads(json_blob)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--trials", type=int, default=12)
    p.add_argument("--budget-thb", type=float, default=150.0)
    p.add_argument("--out", type=Path, default=Path("reports/lab2-tuning.json"))
    args = p.parse_args()

    cfg = config.load()
    adapter = get_adapter(cfg)
    image_uri = os.environ["IMAGE_URI"]
    data_uri = os.environ["DATA_URI"]
    resource_group = os.environ["AZURE_RESOURCE_GROUP"]
    workspace = os.environ["AZURE_WORKSPACE_NAME"]

    price_per_hour_thb = get_hourly_price_thb()
    print(f"Estimated price: {price_per_hour_thb:.2f} THB/hr for {INSTANCE_TYPE} ({REGION})")

    grid = hyperparameter_grid()
    if len(grid) < args.trials:
        raise ValueError(f"grid only has {len(grid)} combos, need >= {args.trials}")

    results: list[dict[str, Any]] = []
    cumulative_cost_thb = 0.0

    try:
        for i, hp in enumerate(grid[: args.trials]):
            if cumulative_cost_thb >= args.budget_thb:
                print(f"STOP: budget of {args.budget_thb} THB reached after {i} trials")
                break

            trial_args = {
                **hp,
                "data-uri": data_uri,
                "experiment": "itcs355-lab2",
                "run-name": f"tune-trial-{i:02d}",
            }

            print(f"[trial {i}] submitting: {hp}")
            start = time.monotonic()
            job_id = adapter.submit_training(image_uri, trial_args)
            try:
                outcome = adapter.wait_training(job_id)
                status = str(outcome["status"])
            except RuntimeError as exc:
                status, outcome = "Failed", {"status": "Failed"}
                print(f"[trial {i}] job failed: {exc}")
            wall_clock_s = time.monotonic() - start

            trial_cost_thb = (wall_clock_s / 3600.0) * price_per_hour_thb
            cumulative_cost_thb += trial_cost_thb

            record: dict[str, Any] = {
                "trial": i,
                "job_id": job_id,
                "status": status,
                "hyperparameters": hp,
                "instance_type": INSTANCE_TYPE,
                "wall_clock_seconds": wall_clock_s,
                "estimated_cost_thb": trial_cost_thb,
                "cumulative_cost_thb": cumulative_cost_thb,
            }

            if status == "Completed":
                try:
                    record.update(fetch_trial_result(job_id, resource_group, workspace))
                except Exception as exc:  # noqa: BLE001
                    record["metrics_fetch_error"] = str(exc)
            else:
                record["error"] = f"job ended with status {status}"

            results.append(record)
            print(json.dumps(record, indent=2))
            print(f"[trial {i}] cumulative cost: {cumulative_cost_thb:.2f} / {args.budget_thb} THB")
    finally:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2))
        print(f"\nWrote {len(results)} trial records to {args.out}")

        completed = [r for r in results if r["status"] == "Completed"]
        if len(completed) < 12:
            print(f"WARNING: only {len(completed)} trials completed "
                  f"(lab requires >= 12) — check budget/errors above")


if __name__ == "__main__":
    main()
