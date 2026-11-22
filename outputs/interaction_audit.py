"""Reproduce the exploratory interaction on the certified M4 sample."""

import hashlib
import json
from pathlib import Path
from statistics import NormalDist

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from political_analysis.models import FORMULAS
from political_analysis.pipeline import verify_dataset_certificate

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
DATA = ROOT / "data/processed/analysis_dataset.csv"
TERMS = ["aging_centered", "aging_centered:oldest_centered"]
FORMULA = FORMULAS["M4"].replace("aging_rate + oldest_share", "aging_centered * oldest_centered")
TOL = {"rtol": 1e-8, "atol": 1e-9}
Z = NormalDist().inv_cdf(0.975)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slope(params, covariance, moderator):
    contrast = np.array([1, moderator])
    return float(contrast @ params), float(np.sqrt(contrast @ covariance @ contrast))


def main():
    plt.switch_backend("Agg")
    a, b = np.meshgrid([-2, 0, 2], [-3, 0, 3])
    synthetic = pd.DataFrame({"a": a.ravel(), "b": b.ravel()})
    synthetic["y"] = 10 + 2 * synthetic.a - synthetic.b + 0.5 * synthetic.a * synthetic.b
    fit = smf.ols("y ~ a * b", synthetic).fit()
    np.testing.assert_allclose(fit.params, [10, 2, -1, 0.5], **TOL)
    np.testing.assert_allclose(
        slope(fit.params[["a", "a:b"]], np.array([[0.09, 0.01], [0.01, 0.04]]), 2),
        [3, np.sqrt(0.29)], **TOL,
    )

    quality = verify_dataset_certificate(DATA, OUT / "data_quality.json")
    prior = json.loads((OUT / "model_validation.json").read_text())
    assert prior["dataset_sha256"] == quality["dataset_sha256"]
    assert prior["model_code_sha256"] == sha(ROOT / "src/political_analysis/models.py")
    for name, digest in prior["artifacts"].items():
        assert sha(OUT / name) == digest, name
    samples = pd.read_csv(OUT / "tables/model_samples.csv", dtype={"sample_id": str})
    ids = samples.loc[(samples.model == "M4") & samples.included, "sample_id"].tolist()
    data = pd.read_csv(DATA, dtype={"region_code": str}).set_index("region_code").loc[ids].copy()
    assert len(data) == len(set(ids)) == 226
    centers = data[["aging_rate", "oldest_share"]].mean()
    data["aging_centered"] = data.aging_rate - centers.aging_rate
    data["oldest_centered"] = data.oldest_share - centers.oldest_share

    baseline = smf.ols(FORMULAS["M4"], data, missing="raise").fit(cov_type="HC3", use_t=False)
    model = smf.ols(FORMULA, data, missing="raise")
    x = model.exog
    rank = int(np.linalg.matrix_rank(x))
    assert rank == x.shape[1] == len(baseline.params) + 1
    leverage = np.square(np.linalg.qr(x, mode="reduced")[0]).sum(axis=1)
    assert (1 - leverage > 1e-12).all()
    assert list(model.data.row_labels) == list(baseline.model.data.row_labels) == ids
    control_terms = baseline.params.index.difference(["aging_rate", "oldest_share"])
    np.testing.assert_array_equal(
        pd.DataFrame(x, columns=model.exog_names)[control_terms],
        pd.DataFrame(baseline.model.exog, columns=baseline.model.exog_names)[control_terms],
    )
    archived = pd.read_csv(OUT / "tables/model_coefficients.csv")
    original = archived.loc[archived.model == "M4"].set_index("term").loc[baseline.params.index]
    np.testing.assert_allclose(original.estimate, baseline.params, **TOL)
    np.testing.assert_allclose(original[["ci_low", "ci_high"]], baseline.conf_int(), **TOL)

    fit = model.fit(cov_type="HC3", use_t=False)
    coef = []
    for name, result in [("M4", baseline), ("M4_interaction", fit)]:
        table = result.conf_int().set_axis(["ci_low", "ci_high"], axis=1)
        coef.append(table.assign(model=name, n=int(result.nobs), estimate=result.params,
                                 se_hc3=result.bse, p_value=result.pvalues))
    coefficient_table = pd.concat(coef).rename_axis("term").reset_index()

    records = []
    for q, raw in data.oldest_share.quantile([0.25, 0.50, 0.75]).items():
        at = raw - centers.oldest_share
        effect, se = slope(fit.params[TERMS], fit.cov_params().loc[TERMS, TERMS], at)
        contrast = pd.Series(0.0, index=fit.params.index)
        contrast.loc[TERMS] = [1, at]
        reference = fit.t_test(contrast.to_numpy())
        np.testing.assert_allclose([effect, se], [reference.effect.item(), reference.sd.item()], **TOL)
        support = data.loc[(data.oldest_share - raw).abs() <= 1, "aging_rate"]
        assert len(support) > 0 and data.oldest_share.min() <= raw <= data.oldest_share.max()
        records.append({
            "quantile": q, "oldest_share_pct": raw, "slope": effect, "se_hc3": se,
            "ci_low": effect - Z * se, "ci_high": effect + Z * se,
            "local_n_within_1pp": len(support), "local_aging_min": support.min(),
            "local_aging_max": support.max(),
        })
    effects = pd.DataFrame(records)
    assert np.isfinite(coefficient_table.select_dtypes("number")).all().all()
    coefficient_path = OUT / "tables/m4_interaction_coefficients.csv"
    effect_path = OUT / "tables/m4_interaction_slopes.csv"
    figure_path = OUT / "figures/m4_interaction_slopes.png"
    coefficient_table.to_csv(coefficient_path, index=False)
    effects.to_csv(effect_path, index=False)
    fig, (ax, hist) = plt.subplots(
        2, 1, sharex=True, figsize=(8, 5.7), height_ratios=[3, 1], layout="constrained"
    )
    ax.axhline(0, color="0.45", linestyle="--", linewidth=1)
    ax.errorbar(effects.oldest_share_pct, effects.slope, yerr=Z * effects.se_hc3,
                fmt="o", color="#19558b", capsize=5, label="Estimate and pointwise 95% CI")
    ax.set(title="Exploratory M4 interaction (226 regions)",
           ylabel="Turnout slope for aging rate\n(pp per 1 pp)")
    ax.legend(loc="best", frameon=False)
    hist.hist(data.oldest_share, bins=20, color="#778da3", edgecolor="white")
    hist.set(xlabel="Share aged 80+ among residents aged 65+ (%)", ylabel="Regions")
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)

    evidence = {
        "gate": "G-M5-03", "dataset_sha256": quality["dataset_sha256"],
        "m4_validation_sha256": sha(OUT / "model_validation.json"), "code_sha256": sha(Path(__file__)),
        "formula": FORMULA, "n": len(ids), "rank": rank, "centers": centers.to_dict(),
        "oldest_share_range": [data.oldest_share.min(), data.oldest_share.max()],
        "synthetic_and_contrast_checks": "PASS",
        "artifacts": {
            str(path.relative_to(OUT)): sha(path) for path in [coefficient_path, effect_path, figure_path]
        },
    }
    (OUT / "interaction_validation.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    )
    print(coefficient_table.loc[coefficient_table.term.isin(TERMS)].to_string(index=False))
    print(effects.to_string(index=False))


if __name__ == "__main__":
    main()
