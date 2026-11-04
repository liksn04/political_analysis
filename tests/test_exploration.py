"""인공 표로 탐색 독립성과 파일 인증 경계를 검사한다."""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from political_analysis.exploration import exploration_tables, run_exploration


@pytest.fixture
def certified_example(tmp_path):
    """실행 경계용 인공 인증서. 공식 수치 검증 증거로 사용하지 않는다."""
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {
            "region_code": ["001", "002"],
            "turnout": [60.0, 70.0],
            "aging_rate": [10.0, 20.0],
            "oldest_share": [5.0, 15.0],
        }
    ).to_csv(data, index=False)
    raw = tmp_path / "source.txt"
    raw.write_text("synthetic source")
    quality = tmp_path / "quality.json"
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
    return data, tmp_path / "out", quality, raw


def test_small_sample_exploration_never_fits_regression(certified_example, monkeypatch):
    from political_analysis import models

    def forbidden(*args, **kwargs):
        raise AssertionError("exploration must not fit regression")

    monkeypatch.setattr(models, "fit_models_with_samples", forbidden)
    monkeypatch.setattr(np, "polyfit", forbidden)
    data, out, quality, raw = certified_example
    result = run_exploration(data, out, quality)
    assert result["observations"] == 2
    assert result["regression_executed_by_exploration"] is False
    assert (out / "figures/scatter_aging_turnout.png").is_file()
    assert not (out / "tables/model_coefficients.csv").exists()
    pairs = pd.read_csv(out / "tables/correlation_pairs.csv")
    assert pairs.n.tolist() == [2, 2, 2]
    assert pairs.pearson_r.tolist() == pytest.approx([1, 1, 1])
    assert pairs.status.tolist() == ["ok"] * 3


@pytest.mark.parametrize(
    "mutation", ["missing_quality", "unverified", "changed_data", "changed_source"]
)
def test_unverified_file_execution_creates_no_outputs(certified_example, mutation, monkeypatch):
    from political_analysis import models

    data, out, quality, raw = certified_example
    if mutation == "missing_quality":
        quality = quality.with_name("absent.json")
    elif mutation == "unverified":
        record = json.loads(quality.read_text())
        record["official_election_totals_verified"] = False
        quality.write_text(json.dumps(record))
    elif mutation == "changed_data":
        with data.open("a") as f:
            f.write("\n")
    else:
        raw.write_text("changed")

    def forbidden(*args, **kwargs):
        raise AssertionError("fit called before verification")

    monkeypatch.setattr(models, "fit_models_with_samples", forbidden)
    for operation in [run_exploration, models.run_analysis]:
        with pytest.raises((ValueError, FileNotFoundError)):
            operation(data, out, quality)
        assert not out.exists()


def test_missing_and_constant_correlations_are_not_zero():
    frame = pd.DataFrame(
        {
            "region_code": [1, 2, 3],
            "turnout": [60.0, 70.0, np.nan],
            "aging_rate": [10.0, 20.0, 30.0],
            "oldest_share": [5.0, 5.0, np.nan],
        }
    )
    descriptive, correlation, pairs = exploration_tables(frame)
    assert "region_code" not in descriptive.index
    assert descriptive.loc["turnout", "count"] == 2
    assert descriptive.loc["turnout", "missing"] == 1
    assert descriptive.loc["aging_rate", "mean"] == 20
    assert correlation.loc["turnout", "aging_rate"] == pytest.approx(1)
    constant = pairs.loc[pairs.y == "oldest_share"]
    assert constant.status.tolist() == ["constant_variable"] * 2
    assert constant.n.tolist() == [2, 2]
    assert constant.pearson_r.isna().all()


def test_all_missing_variable_records_zero_valid_pairs():
    frame = pd.DataFrame(
        {"turnout": [60.0, 70.0], "aging_rate": [10.0, 20.0], "oldest_share": [np.nan, np.nan]}
    )
    desc, correlation, pairs = exploration_tables(frame)
    assert desc.loc["oldest_share", "missing"] == 2
    insufficient = pairs.loc[pairs.y == "oldest_share"]
    assert insufficient.n.tolist() == [0, 0]
    assert insufficient.status.tolist() == ["insufficient_pairs"] * 2
    assert insufficient.pearson_r.isna().all()


@pytest.mark.parametrize("mutation", ["empty", "missing_column", "text", "infinity"])
def test_bad_exploration_schema_rejected(mutation):
    frame = pd.DataFrame(
        {"turnout": [60.0, 70.0], "aging_rate": [10.0, 20.0], "oldest_share": [5.0, 15.0]}
    )
    if mutation == "empty":
        frame = frame.iloc[:0]
    elif mutation == "missing_column":
        frame = frame.drop(columns="oldest_share")
    elif mutation == "text":
        frame["turnout"] = ["bad", "70"]
    else:
        frame.loc[0, "aging_rate"] = np.inf
    with pytest.raises(ValueError):
        exploration_tables(frame)


def test_zero_complete_scatter_pairs_produces_explicit_empty_plot(certified_example):
    data, out, quality, raw = certified_example
    frame = pd.read_csv(data)
    frame["turnout"] = np.nan
    frame.to_csv(data, index=False)
    record = json.loads(quality.read_text())
    record["dataset_sha256"] = hashlib.sha256(data.read_bytes()).hexdigest()
    quality.write_text(json.dumps(record))
    result = run_exploration(data, out, quality)
    assert result["scatter_status"] == "no_complete_pairs"
    assert result["scatter_complete_pairs"] == 0
    assert (out / "figures/scatter_aging_turnout.png").is_file()


def test_verified_model_entry_still_fits_and_writes_tables(certified_example, monkeypatch):
    from political_analysis import models

    data, out, quality, raw = certified_example
    seen = []

    def synthetic_fit(frame):
        seen.append(len(frame))
        return (
            pd.DataFrame({"estimate": [0.0]}),
            pd.DataFrame({"model": ["synthetic_test"], "n": [2]}),
            pd.DataFrame({"sample_id": ["001", "002"], "included": [True, True]}),
        )

    monkeypatch.setattr(models, "fit_models_with_samples", synthetic_fit)
    models.run_analysis(data, out, quality)
    assert seen == [2]
    assert (out / "tables/model_coefficients.csv").exists()
    assert (out / "tables/correlation_pairs.csv").exists()
