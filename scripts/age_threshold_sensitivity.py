"""Re-estimate the baseline regional model at age thresholds 75, 80, and 85."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from political_analysis.models import fit_models_with_samples
from political_analysis.pipeline import _attach, verify_dataset_certificate

THRESHOLDS = (75, 80, 85)
TOLERANCE = {"atol": 1e-9, "rtol": 1e-8}


def run(run_dir: Path, population_path: Path, crosswalk_path: Path) -> None:
    data_path = run_dir / "analysis_dataset.csv"
    certificate = verify_dataset_certificate(data_path, run_dir / "data_quality.json")
    for path in (population_path, crosswalk_path):
        if str(path.resolve()) not in certificate["verified_files"]:
            raise ValueError(f"Input is missing from the verified certificate: {path}")

    data = pd.read_csv(data_path, dtype={"region_code": "string"})
    population = pd.read_csv(population_path, dtype={"source_region_code": "string"})
    crosswalk = pd.read_csv(
        crosswalk_path, dtype={"source_region_code": "string", "region_code": "string"}
    )
    ages = _attach(population, crosswalk, "population")
    counts = pd.DataFrame({
        age: ages.loc[ages["age"] >= age].groupby("region_code")["population"].sum()
        for age in (65, *THRESHOLDS)
    }).reindex(data["region_code"])
    if counts.isna().any().any() or (counts[65] <= 0).any():
        raise ValueError("Missing threshold counts or nonpositive 65+ population")
    if counts.diff(axis=1).iloc[:, 1:].gt(0).any().any():
        raise ValueError("Cumulative age counts must be non-increasing")
    np.testing.assert_array_equal(counts[65], data["population_65plus"])
    np.testing.assert_array_equal(counts[80], data["population_80plus"])
    shares = counts[list(THRESHOLDS)].div(counts[65], axis=0) * 100
    np.testing.assert_allclose(shares[80], data["oldest_share"], **TOLERANCE)

    base_coefficients, _, base_samples = fit_models_with_samples(data)
    base_ids = base_samples.query("model == 'M4' and included")["sample_id"].tolist()
    if len(base_ids) != 226:
        raise ValueError(f"Expected 226 base M4 regions, got {len(base_ids)}")

    results = []
    for age in THRESHOLDS:
        model_data = data.assign(oldest_share=shares[age].to_numpy())
        coefficients, _, samples = fit_models_with_samples(model_data)
        region_ids = samples.query("model == 'M4' and included")["sample_id"].tolist()
        if region_ids != base_ids:
            raise ValueError(f"The M4 region list changed at age threshold {age}")
        if age == 80:
            numeric = ["estimate", "std_error_hc3", "ci_low", "ci_high"]
            expected = base_coefficients.query("model == 'M4'").set_index("term")[numeric]
            observed = coefficients.query("model == 'M4'").set_index("term")[numeric]
            if not expected.index.equals(observed.index):
                raise ValueError("Age 80 estimate has a different set of M4 terms")
            np.testing.assert_allclose(observed, expected, **TOLERANCE)
        focal = coefficients.query("model == 'M4' and term == 'oldest_share'").iloc[0]
        q25, q75 = shares.loc[base_ids, age].quantile([0.25, 0.75])
        iqr = q75 - q25
        results.append({
            "age_threshold": age,
            "n": len(region_ids),
            "estimate": focal["estimate"],
            "std_error_hc3": focal["std_error_hc3"],
            "ci_low": focal["ci_low"],
            "ci_high": focal["ci_high"],
            "q25": q25,
            "q75": q75,
            "iqr": iqr,
            "iqr_estimate": focal["estimate"] * iqr,
            "iqr_ci_low": focal["ci_low"] * iqr,
            "iqr_ci_high": focal["ci_high"] * iqr,
        })

    table_dir = run_dir / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    output = table_dir / "age_threshold_sensitivity.csv"
    pd.DataFrame(results).to_csv(output, index=False)
    counts.add_prefix("population_").add_suffix("plus").to_csv(
        table_dir / "age_threshold_counts.csv"
    )
    print(f"Validated counts, age 80 baseline and common M4 sample. Wrote {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--population", type=Path, default=Path("data/interim/population.csv"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/reference/region_crosswalk.csv"))
    args = parser.parse_args()
    run(args.run_dir, args.population, args.crosswalk)
