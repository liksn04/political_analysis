"""Reproduce G-M5-01 comparisons from the certified M4 results."""

import hashlib
import json
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from political_analysis.models import FORMULAS
from political_analysis.pipeline import verify_dataset_certificate

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
DATA = ROOT / "data/processed/analysis_dataset.csv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit():
    quality = verify_dataset_certificate(DATA, OUT / "data_quality.json")
    prior = json.loads((OUT / "model_validation.json").read_text())
    assert prior["dataset_sha256"] == quality["dataset_sha256"]
    assert prior["model_code_sha256"] == digest(ROOT / "src/political_analysis/models.py")
    assert prior["text_review"] == "PASS"
    for name, expected_hash in prior["artifacts"].items():
        assert digest(OUT / name) == expected_hash, name

    data = pd.read_csv(DATA, dtype={"region_code": str}).set_index("region_code", drop=False)
    summary = pd.read_csv(OUT / "tables/model_summary.csv").set_index("model")
    samples = pd.read_csv(OUT / "tables/model_samples.csv", dtype={"sample_id": str})
    coefficients = pd.read_csv(OUT / "tables/model_coefficients.csv").set_index(["model", "term"])
    ids = {name: set(rows.loc[rows.included, "sample_id"]) for name, rows in samples.groupby("model")}
    common_models = ["M1_common", "M2_common", "M3_common", "M4"]
    assert all(ids[name] == ids["M4"] for name in [*common_models, "M4_WLS"])
    assert all(summary.at[name, "n"] == len(region_ids) for name, region_ids in ids.items())
    special = set(data.index[data.region_type == "특수지역"])
    assert special == {"3600000000", "5000000000"}
    assert set(data.index) - ids["M4"] == special

    controls = data.loc[data.index.isin(ids["M4"])]
    weights = controls.electors.to_numpy()
    assert np.isfinite(weights).all() and (weights > 0).all()
    design_fields = [
        "formula", "design_columns", "covariance", "ci_distribution",
        "region_type_reference", "province_reference",
    ]
    assert summary.loc["M4", design_fields].equals(summary.loc["M4_WLS", design_fields])
    assert summary.at["M4", "formula"] == FORMULAS["M4"]
    ols = smf.ols(FORMULAS["M4"], controls, missing="raise")
    wls = smf.wls(FORMULAS["M4"], controls, weights=weights, missing="raise")
    np.testing.assert_array_equal(ols.exog, wls.exog)
    np.testing.assert_array_equal(ols.endog, wls.endog)
    np.testing.assert_array_equal(wls.weights, weights)
    assert ols.exog_names == wls.exog_names == json.loads(summary.at["M4", "design_columns"])

    # QR on the weighted system gives an independent check of the archived fit.
    q, r = np.linalg.qr(wls.wexog, mode="reduced")
    beta = np.linalg.solve(r, q.T @ wls.wendog)
    residual = wls.wendog - wls.wexog @ beta
    adjusted = residual / (1 - (q**2).sum(axis=1))
    influence = np.linalg.solve(r, q.T * adjusted)
    se = np.linalg.norm(influence, axis=1)
    z = NormalDist().inv_cdf(0.975)
    terms = wls.exog_names
    columns = ["estimate", "std_error_hc3", "ci_low", "ci_high"]
    archived = coefficients.loc["M4_WLS"].loc[terms, columns]
    np.testing.assert_allclose(
        archived, np.column_stack([beta, se, beta - z * se, beta + z * se]),
        rtol=1e-8, atol=1e-9,
    )

    pairs = [("weight", "M4", "M4_WLS")]
    pairs += [("common_controls", left, right) for left, right in zip(common_models[:-1], common_models[1:])]
    for base in ["M1", "M2", "M3"]:
        common = base + "_common"
        assert summary.at[base, "formula"] == summary.at[common, "formula"] == FORMULAS[base]
        assert ids[base] == ids[common] | special
        pairs.append(("special_exclusion", base, common))

    comparisons = []
    for kind, left, right in pairs:
        for term in ["aging_rate", "oldest_share"]:
            before = coefficients.loc[left].reindex([term]).iloc[0]
            after = coefficients.loc[right].reindex([term]).iloc[0]
            if pd.isna(before.estimate) and pd.isna(after.estimate):
                continue
            row = {"comparison": kind, "left": left, "right": right, "term": term}
            for side, model, result in [("left", left, before), ("right", right, after)]:
                row[side + "_n"] = len(ids[model])
                for column in ["estimate", "ci_low", "ci_high", "p_value"]:
                    row[side + "_" + column] = result[column]
            row["delta_right_minus_left"] = after.estimate - before.estimate
            comparisons.append(row)

    full = smf.ols(FORMULAS["M4"], data, missing="raise")
    rank = int(np.linalg.matrix_rank(full.exog))
    singleton_provinces = sorted(data.loc[list(special), "province"])
    assert all(int(data.province.eq(province).sum()) == 1 for province in singleton_provinces)
    columns = pd.DataFrame(full.exog, columns=full.exog_names, index=data.index)
    np.testing.assert_array_equal(
        columns["C(region_type)[T.특수지역]"],
        columns[[f"C(province)[T.{province}]" for province in singleton_provinces]].sum(axis=1),
    )
    assert rank < full.exog.shape[1]

    table = OUT / "tables/robustness_comparisons.csv"
    pd.DataFrame(comparisons).to_csv(table, index=False)
    return {
        "gate": "G-M5-01",
        "dataset_sha256": quality["dataset_sha256"],
        "m4_validation_sha256": digest(OUT / "model_validation.json"),
        "audit_code_sha256": digest(Path(__file__)),
        "comparison_table_sha256": digest(table),
        "same_id_set_n": len(ids["M4"]),
        "weight_min": int(weights.min()),
        "weight_max": int(weights.max()),
        "wls_hc3_values_rechecked": len(terms) * 4,
        "special_excluded_ids": sorted(special),
        "m4_including_special": {
            "status": "NOT_APPLICABLE",
            "n": len(data),
            "rank": rank,
            "design_columns": full.exog.shape[1],
            "singleton_provinces": singleton_provinces,
        },
    }


if __name__ == "__main__":
    evidence = json.dumps(audit(), ensure_ascii=False, indent=2) + "\n"
    (OUT / "robustness_validation.json").write_text(evidence)
    print(evidence, end="")
