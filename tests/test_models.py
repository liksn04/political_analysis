"""회귀모형은 인공 데이터만 사용해 계산 경로를 검사한다."""

import numpy as np
import pandas as pd

from political_analysis.models import fit_models


def test_fits_models_with_hc3_and_common_sample() -> None:
    rng = np.random.default_rng(20261103)
    n = 72
    index = np.arange(n)
    aging = 18 + rng.uniform(0, 25, size=n)
    oldest = 15 + rng.uniform(0, 25, size=n)
    fiscal = rng.uniform(12, 55, size=n)
    migration = rng.normal(0, 1, size=n)
    population = rng.integers(20000, 500000, size=n)
    turnout = (
        62 + 0.25 * aging - 0.12 * oldest + 0.025 * fiscal
        + rng.normal(0, 2, size=n)
    )
    frame = pd.DataFrame(
        {
            "turnout": turnout,
            "aging_rate": aging,
            "oldest_share": oldest,
            "fiscal_independence": fiscal,
            "net_migration_rate": migration,
            "log_population": np.log(population),
            "electors": np.round(population * 0.8).astype(int),
            "region_type": np.array(["시", "군", "자치구"])[index % 3],
            "province": np.array(["가상도1", "가상도2", "가상도3", "가상도4"])[index % 4],
        }
    )
    frame.loc[0, "region_type"] = "특수지역"
    frame.loc[1, "fiscal_independence"] = np.nan

    coef, summary = fit_models(frame)
    assert {"M1", "M2", "M3", "M4", "M4_WLS", "M1_common", "M2_common", "M3_common"} == set(
        summary["model"]
    )
    assert not coef.empty
    assert (summary["covariance"] == "HC3").all()
    assert summary.set_index("model").loc["M4", "n"] == 70
    assert summary.set_index("model").loc["M3", "n"] == 71
    assert summary.set_index("model").loc["M2_common", "n"] == 70
