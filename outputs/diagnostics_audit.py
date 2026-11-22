"""Reproduce G-M5-02 diagnostics against the certified M4 OLS design."""

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from statsmodels.stats.outliers_influence import variance_inflation_factor

from political_analysis.models import FORMULAS, MODEL_VARIABLES
from political_analysis.pipeline import verify_dataset_certificate

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
DATA = ROOT / "data/processed/analysis_dataset.csv"
TOL = {"rtol": 1e-8, "atol": 1e-9}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def standardized_design(x):
    """Keep the intercept and put every other column on a common scale."""
    columns = x[:, 1:]
    return np.column_stack([x[:, 0], (columns - columns.mean(axis=0)) / columns.std(axis=0)])


def influence(fit):
    x = fit.model.exog
    q, _ = np.linalg.qr(x, mode="reduced")
    leverage = np.square(q).sum(axis=1)
    cook = fit.resid**2 * leverage / (x.shape[1] * fit.mse_resid * (1 - leverage)**2)
    return leverage, cook


def check_synthetic():
    u = np.array([1, -1, 1, -1])
    v = np.array([1, 1, -1, -1])
    x = sm.add_constant(np.column_stack([u, 2 * u + v]))
    np.testing.assert_allclose([variance_inflation_factor(x, i) for i in [1, 2]], [5, 5], **TOL)

    x = sm.add_constant(np.array([0, 1, 2, 3, 4, 5, 6, 25]))
    y = np.array([0, 2, 1, 3, 3, 5, 5, 31])
    fit = sm.OLS(y, x).fit()
    leverage, cook = influence(fit)
    assert leverage[-1] > 2 * x.shape[1] / len(y)
    assert cook[-1] > 4 / len(y)
    deleted = sm.OLS(y[:-1], x[:-1]).fit()
    fitted_shift = x @ (fit.params - deleted.params)
    np.testing.assert_allclose(cook[-1], fitted_shift @ fitted_shift / (2 * fit.mse_resid), **TOL)


def audit():
    check_synthetic()
    quality = verify_dataset_certificate(DATA, OUT / "data_quality.json")
    prior = json.loads((OUT / "model_validation.json").read_text())
    sensitivity = json.loads((OUT / "robustness_validation.json").read_text())
    assert sensitivity["m4_validation_sha256"] == sha(OUT / "model_validation.json")
    assert prior["dataset_sha256"] == quality["dataset_sha256"]
    assert prior["model_code_sha256"] == sha(ROOT / "src/political_analysis/models.py")
    for name, expected in prior["artifacts"].items():
        assert sha(OUT / name) == expected, name

    data = pd.read_csv(DATA, dtype={"region_code": str}).set_index("region_code", drop=False)
    samples = pd.read_csv(OUT / "tables/model_samples.csv", dtype={"sample_id": str})
    summary = pd.read_csv(OUT / "tables/model_summary.csv").set_index("model")
    archived = pd.read_csv(OUT / "tables/model_coefficients.csv").set_index(["model", "term"])
    ids = samples.loc[(samples.model == "M4") & samples.included, "sample_id"].tolist()
    assert ids == samples.loc[(samples.model == "M3_common") & samples.included, "sample_id"].tolist()
    assert len(ids) == len(set(ids)) == int(summary.at["M4", "n"])
    sample = data.loc[ids]
    model = smf.ols(FORMULAS["M4"], sample, missing="raise")
    baseline = model.fit(cov_type="HC3", use_t=False)
    m3 = smf.ols(FORMULAS["M3"], sample, missing="raise").fit(cov_type="HC3", use_t=False)
    x, y = model.exog, model.endog
    n, p = x.shape
    assert model.exog_names == json.loads(summary.at["M4", "design_columns"])
    rank = int(np.linalg.matrix_rank(x))
    assert rank == p == summary.at["M4", "design_rank"]
    for name, fit in [("M4", baseline), ("M3_common", m3)]:
        original = archived.loc[name].loc[fit.params.index]
        np.testing.assert_allclose(original.estimate, fit.params, **TOL)
        np.testing.assert_allclose(original.std_error_hc3, fit.bse, **TOL)
        np.testing.assert_allclose(original[["ci_low", "ci_high"]], fit.conf_int(), **TOL)

    terms = MODEL_VARIABLES["M3"][1:]
    continuous = standardized_design(sm.add_constant(sample[terms].to_numpy()))
    full_scaled = standardized_design(x)
    vif = pd.DataFrame(
        {
            "term": terms,
            "continuous_only": [variance_inflation_factor(continuous, i) for i in range(1, 6)],
            "with_fixed_effects": [
                variance_inflation_factor(full_scaled, model.exog_names.index(term)) for term in terms
            ],
        }
    )
    vif["flag_continuous_only"] = vif.continuous_only >= 5
    vif["flag_with_fixed_effects"] = vif.with_fixed_effects >= 5

    leverage, cook = influence(baseline)
    reference = baseline.get_influence()
    np.testing.assert_allclose(leverage, reference.hat_matrix_diag, **TOL)
    np.testing.assert_allclose(cook, reference.cooks_distance[0], **TOL)
    np.testing.assert_allclose(leverage.sum(), p, **TOL)
    np.testing.assert_allclose(leverage.max(), summary.at["M4", "max_leverage"], **TOL)
    leverage_cut, cook_cut = 2 * p / n, 4 / n
    regions = sample[["region_code", "region_name", "province", "region_type"]].copy()
    regions["fitted"] = baseline.fittedvalues
    regions["residual"] = baseline.resid
    regions["leverage"] = leverage
    regions["cooks_distance"] = cook
    regions["high_leverage"] = leverage > leverage_cut
    regions["excluded_in_sensitivity"] = cook > cook_cut
    excluded = regions.loc[regions.excluded_in_sensitivity].sort_values("cooks_distance", ascending=False)
    keep = ~regions.excluded_in_sensitivity.to_numpy()
    x_reduced = x[keep]
    rank_reduced = int(np.linalg.matrix_rank(x_reduced))
    q_reduced, _ = np.linalg.qr(x_reduced, mode="reduced")
    max_reduced_leverage = float(np.square(q_reduced).sum(axis=1).max())
    refit_ok = keep.sum() > p and rank_reduced == p and 1 - max_reduced_leverage > 1e-12
    fitted_models = [("M4", baseline, n)]
    if refit_ok:
        reduced = sm.OLS(y[keep], x_reduced, hasconst=True).fit(cov_type="HC3", use_t=False)
        fitted_models.append(("M4_exclude_cook", reduced, int(keep.sum())))
    coefficient_rows = []
    for name, fit, count in fitted_models:
        for i, term in enumerate(model.exog_names):
            ci_low, ci_high = np.asarray(fit.conf_int())[i]
            coefficient_rows.append(
                {
                    "model": name, "n": count, "term": term,
                    "estimate": np.asarray(fit.params)[i], "std_error_hc3": np.asarray(fit.bse)[i],
                    "p_value": np.asarray(fit.pvalues)[i], "ci_low": ci_low, "ci_high": ci_high,
                }
            )
    coefficient_table = pd.DataFrame(coefficient_rows)
    assert np.isfinite(coefficient_table.select_dtypes("number")).all().all()

    province_rows = []
    for name, fit in [("M3_common", m3), ("M4", baseline)]:
        residual = sample[["province"]].assign(residual=fit.resid)
        for province, rows in residual.groupby("province"):
            e = rows.residual
            province_rows.append(
                {
                    "model": name, "province": province, "n": len(e), "mean": e.mean(),
                    "sd": e.std(), "rmse": np.sqrt((e**2).mean()), "min": e.min(), "max": e.max(),
                }
            )
    province_table = pd.DataFrame(province_rows)
    np.testing.assert_allclose(province_table.loc[province_table.model == "M4", "mean"], 0, **TOL)

    tables = {
        "m4_vif.csv": vif, "m4_influence.csv": regions, "m4_cook_exclusions.csv": excluded,
        "m4_cook_sensitivity.csv": coefficient_table, "m4_province_residuals.csv": province_table,
    }
    for name, table in tables.items():
        table.to_csv(OUT / "tables" / name, index=False)

    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    ax.scatter(leverage[keep], cook[keep], s=25, alpha=0.7, label="Retained (sensitivity)")
    ax.scatter(leverage[~keep], cook[~keep], s=32, label="Cook-flagged (excluded in sensitivity)")
    ax.axvline(leverage_cut, color="0.4", linestyle=":", label=f"Leverage screen {leverage_cut:.3f}")
    ax.axhline(cook_cut, color="0.4", linestyle="--", label=f"Cook screen {cook_cut:.3f}")
    ax.set(xlabel="Leverage (hat diagonal)", ylabel="Cook's distance", title=f"M4 influence diagnostics (n={n})")
    ax.legend(loc="upper left", fontsize=8)
    fig_path = OUT / "figures/m4_influence.png"
    fig.savefig(fig_path, dpi=160)
    plt.close(fig)

    raw_condition = float(np.linalg.cond(x))
    np.testing.assert_allclose(raw_condition, summary.at["M4", "condition_number"], **TOL)
    return {
        "gate": "G-M5-02",
        "dataset_sha256": quality["dataset_sha256"],
        "m4_validation_sha256": sha(OUT / "model_validation.json"),
        "code_sha256": sha(Path(__file__)),
        "n": n, "p": p, "rank": rank,
        "condition_raw": raw_condition,
        "condition_full_scaled": float(np.linalg.cond(full_scaled)),
        "condition_continuous_scaled": float(np.linalg.cond(continuous)),
        "leverage_threshold": leverage_cut, "cook_threshold": cook_cut,
        "high_leverage_n": int(regions.high_leverage.sum()),
        "cook_excluded_ids": excluded.region_code.tolist(),
        "refit_status": "PASS" if refit_ok else "NOT_APPLICABLE",
        "refit_n": int(keep.sum()), "refit_rank": rank_reduced,
        "refit_max_leverage": max_reduced_leverage,
        "synthetic_vif_and_influence_checks": "PASS",
        "artifacts": {str(path.relative_to(OUT)): sha(path) for path in [fig_path, *(
            OUT / "tables" / name for name in tables
        )]},
    }


if __name__ == "__main__":
    report = json.dumps(audit(), ensure_ascii=False, indent=2) + "\n"
    (OUT / "diagnostics_validation.json").write_text(report)
    print(report, end="")
