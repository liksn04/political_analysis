"""회귀모형은 인공 데이터만 사용해 계산 경로를 검사한다."""

import numpy as np
import pandas as pd
import pytest

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
    turnout = 62 + 0.25 * aging - 0.12 * oldest + 0.025 * fiscal + rng.normal(0, 2, size=n)
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


def synthetic_model_frame():
    """독립 수치 검증용 고정 인공 자료이며 실제 연구 관측치가 아니다."""
    rng = np.random.default_rng(4101)
    n = 144
    i = np.arange(n)
    frame = pd.DataFrame(
        {
            "region_code": [f"SYN{j:03d}" for j in i],
            "region_name": [f"인공지역{j}" for j in i],
            "aging_rate": rng.uniform(15, 45, n),
            "oldest_share": rng.uniform(12, 35, n),
            "fiscal_independence": rng.uniform(10, 50, n),
            "net_migration_rate": rng.normal(0, 1, n),
            "log_population": rng.uniform(10, 13, n),
            "electors": rng.integers(10000, 500000, n).astype(float),
            "region_type": np.array(["시", "군", "자치구"])[i % 3],
            "province": np.array(["가상도1", "가상도2", "가상도3", "가상도4"])[i % 4],
        }
    )
    frame["turnout"] = (
        62
        + 0.2 * frame.aging_rate
        - 0.1 * frame.oldest_share
        + 0.03 * frame.fiscal_independence
        + 0.1 * frame.net_migration_rate
        - 0.2 * frame.log_population
        + rng.normal(0, 1.4, n)
    )
    frame.loc[0, "region_type"] = "특수지역"
    frame.loc[1, "fiscal_independence"] = np.nan
    frame.loc[2, "electors"] = np.nan
    return frame


def independent_matrix_result(data, name):
    """statsmodels/patsy와 생산 모형 변수를 가져오지 않고 정상방정식·HC3를 계산한다."""
    import math
    from statistics import NormalDist

    variables = {
        "M1": ["aging_rate"],
        "M2": ["aging_rate", "oldest_share"],
        "M3": [
            "aging_rate",
            "oldest_share",
            "fiscal_independence",
            "net_migration_rate",
            "log_population",
        ],
        "M4": [
            "aging_rate",
            "oldest_share",
            "fiscal_independence",
            "net_migration_rate",
            "log_population",
        ],
    }
    base = name.split("_")[0]
    common = name.endswith("_common")
    weighted = name == "M4_WLS"
    needed = ["turnout"] + variables["M4" if common else base]
    if base == "M4" or common:
        needed += ["region_type", "province"]
    if weighted:
        needed += ["electors"]
    mask = data[needed].notna().all(axis=1)
    if base == "M4" or common:
        mask &= data.region_type.ne("특수지역")
    sample = data.loc[mask]
    columns = {"Intercept": np.ones(len(sample))}
    columns.update({v: sample[v].to_numpy(float) for v in variables[base]})
    if base == "M4":
        for factor in ["region_type", "province"]:
            for level in sorted(sample[factor].unique())[1:]:
                columns[f"C({factor})[T.{level}]"] = sample[factor].eq(level).to_numpy(float)
    terms = list(columns)
    x = np.column_stack(list(columns.values()))
    y = sample.turnout.to_numpy(float)
    weights = sample.electors.to_numpy(float) if weighted else np.ones(len(sample))
    xw = x * np.sqrt(weights)[:, None]
    yw = y * np.sqrt(weights)
    bread = np.linalg.inv(xw.T @ xw)
    beta = np.linalg.solve(xw.T @ xw, xw.T @ yw)
    error = yw - xw @ beta
    h = np.einsum("ij,jk,ik->i", xw, bread, xw)
    covariance = bread @ (xw.T @ ((error / (1 - h))[:, None] ** 2 * xw)) @ bread
    se = np.sqrt(np.diag(covariance))
    z = NormalDist().inv_cdf(0.975)
    p = [math.erfc(abs(b / s) / math.sqrt(2)) for b, s in zip(beta, se)]
    coefficients = pd.DataFrame(
        {
            "estimate": beta,
            "std_error_hc3": se,
            "p_value": p,
            "ci_low": beta - z * se,
            "ci_high": beta + z * se,
        },
        index=terms,
    )
    centered = y - np.average(y, weights=weights)
    r2 = 1 - np.sum(error**2) / np.sum(weights * centered**2)
    return (
        coefficients,
        sample.region_code.tolist(),
        {
            "n": len(sample),
            "p": len(terms),
            "df_resid": len(sample) - len(terms),
            "r_squared": r2,
            "adj_r_squared": 1 - (1 - r2) * (len(sample) - 1) / (len(sample) - len(terms)),
        },
    )


def test_all_eight_models_match_independent_matrix_calculations():
    from political_analysis.models import fit_models_with_samples

    frame = synthetic_model_frame()
    coef, summary, samples = fit_models_with_samples(frame)
    for row in summary.to_dict("records"):
        expected, ids, stats = independent_matrix_result(frame, row["model"])
        actual = coef.loc[coef.model == row["model"]].set_index("term")
        assert set(actual.index) == set(expected.index)
        for col in expected:
            np.testing.assert_allclose(
                actual.loc[expected.index, col], expected[col], rtol=1e-8, atol=1e-9
            )
        actual_ids = samples.loc[
            (samples.model == row["model"]) & samples.included, "sample_id"
        ].tolist()
        assert actual_ids == ids
        assert row["n"] == stats["n"] and row["parameters"] == stats["p"] == row["design_rank"]
        assert row["df_resid"] == stats["df_resid"]
        np.testing.assert_allclose(
            [row["r_squared"], row["adj_r_squared"]],
            [stats["r_squared"], stats["adj_r_squared"]],
            rtol=1e-10,
            atol=1e-10,
        )
        assert row["ci_distribution"] == "normal"


def test_common_sample_follows_m4_not_missing_wls_weight():
    from political_analysis.models import fit_models_with_samples

    frame = synthetic_model_frame()
    _, summary, samples = fit_models_with_samples(frame)
    groups = {name: set(g.loc[g.included, "sample_id"]) for name, g in samples.groupby("model")}
    assert groups["M4"] == groups["M1_common"] == groups["M2_common"] == groups["M3_common"]
    assert "SYN002" in groups["M4"] and "SYN002" not in groups["M4_WLS"]
    assert (
        samples.loc[
            (samples.model == "M4_WLS") & (samples.sample_id == "SYN002"), "exclusion_reason"
        ].item()
        == "missing:electors"
    )
    assert (
        "special_region_policy"
        in samples.loc[
            (samples.model == "M4") & (samples.sample_id == "SYN000"), "exclusion_reason"
        ].item()
    )
    m4 = summary.set_index("model").loc["M4"]
    assert m4.region_type_reference == "군" and m4.province_reference == "가상도1"


def test_unused_categorical_levels_do_not_create_singular_columns():
    from political_analysis.models import fit_models_with_samples

    frame = synthetic_model_frame()
    frame["region_type"] = pd.Categorical(
        frame.region_type, categories=["군", "시", "자치구", "특수지역", "미사용"]
    )
    frame["province"] = pd.Categorical(
        frame.province, categories=["가상도1", "가상도2", "가상도3", "가상도4", "미사용도"]
    )
    _, summary, _ = fit_models_with_samples(frame)
    assert (summary.design_rank == summary.parameters).all()
    assert not summary.design_columns.str.contains("미사용").any()


def test_missing_category_affects_only_requiring_models():
    from political_analysis.models import fit_models_with_samples

    frame = synthetic_model_frame()
    frame.loc[3, "province"] = None
    _, summary, samples = fit_models_with_samples(frame)
    selected = summary.set_index("model")
    assert selected.loc["M1", "n"] == 144 and selected.loc["M4", "n"] == 141
    assert selected.loc["M1_common", "n"] == 141
    assert (
        "missing:province"
        in samples.loc[
            (samples.model == "M4") & (samples.sample_id == "SYN003"), "exclusion_reason"
        ].item()
    )


def test_duplicate_dataframe_index_preserves_unique_region_rows():
    from political_analysis.models import fit_models_with_samples

    frame = synthetic_model_frame()
    frame.index = [0] * len(frame)
    _, _, samples = fit_models_with_samples(frame)
    assert not samples.duplicated(["model", "sample_id"]).any()
    assert len(samples) == 144 * 8


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "missing_column",
        "bad_numeric",
        "infinite",
        "zero_weight",
        "constant_predictor",
        "collinear",
        "constant_outcome",
        "too_few",
        "singleton_province",
        "duplicate_code",
        "unknown_type",
    ],
)
def test_invalid_model_contract_rejected(mutation):
    from political_analysis.models import fit_models_with_samples

    frame = synthetic_model_frame()
    if mutation == "empty":
        frame = frame.iloc[:0]
    elif mutation == "missing_column":
        frame = frame.drop(columns="oldest_share")
    elif mutation == "bad_numeric":
        frame["aging_rate"] = "bad"
    elif mutation == "infinite":
        frame.loc[3, "aging_rate"] = np.inf
    elif mutation == "zero_weight":
        frame.loc[3, "electors"] = 0
    elif mutation == "constant_predictor":
        frame["aging_rate"] = 1.0
    elif mutation == "collinear":
        frame["oldest_share"] = frame.aging_rate * 2
    elif mutation == "constant_outcome":
        frame["turnout"] = 70.0
    elif mutation == "too_few":
        frame = frame.iloc[:2]
    elif mutation == "singleton_province":
        frame.loc[3, "province"] = "고립된도"
    elif mutation == "duplicate_code":
        frame.loc[3, "region_code"] = frame.loc[4, "region_code"]
    else:
        frame.loc[3, "region_type"] = "없는유형"
    with pytest.raises(ValueError):
        fit_models_with_samples(frame)


def test_nonfinite_estimation_result_not_reported_as_success(monkeypatch):
    from political_analysis import models

    original = models.smf.ols

    def broken_factory(*args, **kwargs):
        model = original(*args, **kwargs)
        fit = model.fit

        def broken_fit(*args, **kwargs):
            result = fit(*args, **kwargs)
            result.conf_int = lambda alpha: pd.DataFrame(
                np.inf, index=result.params.index, columns=[0, 1]
            )
            return result

        model.fit = broken_fit
        return model

    monkeypatch.setattr(models.smf, "ols", broken_factory)
    with pytest.raises(ValueError, match="유한하지 않은 추정"):
        models.fit_models_with_samples(synthetic_model_frame())


def test_file_entry_writes_sample_and_manifest_without_real_research_fit(tmp_path):
    import hashlib
    import json

    from political_analysis.models import run_analysis

    frame = synthetic_model_frame()
    data = tmp_path / "synthetic.csv"
    frame.to_csv(data, index=False)
    raw = tmp_path / "synthetic_source.txt"
    raw.write_text("test-only source")
    quality = tmp_path / "synthetic_quality.json"
    quality.write_text(
        json.dumps(
            {
                "input_contract_verified": True,
                "official_election_totals_verified": True,
                "dataset_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
                "verified_files": {str(raw): hashlib.sha256(raw.read_bytes()).hexdigest()},
            }
        )
    )
    output = tmp_path / "out"
    run_analysis(data, output, quality)
    summary = pd.read_csv(output / "tables/model_summary.csv")
    samples = pd.read_csv(output / "tables/model_samples.csv")
    counts = samples.loc[samples.included].groupby("model").size()
    assert counts.to_dict() == summary.set_index("model").n.to_dict()
    manifest = json.loads((output / "model_manifest.json").read_text())
    for name, digest in manifest["artifacts"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert manifest["dataset_sha256"] == hashlib.sha256(data.read_bytes()).hexdigest()
