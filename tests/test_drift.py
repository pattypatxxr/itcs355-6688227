"""Lab 4 — the drift threshold must be justified by data, and this keeps it honest.

PSI between two samples of the SAME distribution is not zero: it is sampling noise that
depends on the window size. The threshold has to sit above that noise and below the smallest
shift we care about. Both sides are re-measured here, so editing the threshold without
evidence makes a test fail.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from monitoring.drift import PSI_MODERATE, psi
from src import config

RAW = config.REPO_ROOT / "data" / "raw" / "sensors.csv"
WINDOW = 500  # the size of the rolling window the service keeps


@pytest.fixture(scope="module")
def temp():
    if not RAW.exists():
        pytest.skip("run `make data` first")
    return pd.read_csv(RAW)["temp_c"].to_numpy(float)


def test_threshold_sits_above_sampling_noise(temp):
    rng = np.random.default_rng(0)
    worst = max(psi(temp, rng.choice(temp, WINDOW, replace=False)) for _ in range(300))
    assert worst < PSI_MODERATE, (
        f"unshifted windows reach PSI {worst:.3f}; a threshold of {PSI_MODERATE} would false-alarm"
    )


def test_threshold_catches_a_three_degree_shift(temp):
    rng = np.random.default_rng(1)
    scores = [psi(temp, rng.choice(temp, WINDOW, replace=False) + 3.0) for _ in range(300)]
    assert np.median(scores) > PSI_MODERATE, (
        f"median PSI {np.median(scores):.3f} for a +3 degC shift is below the {PSI_MODERATE} threshold"
    )
