"""실제 선거자료가 아닌 작은 인공 예제로 파이프라인을 검증한다."""

from pathlib import Path

import pandas as pd
import pytest

from political_analysis.pipeline import build_dataset


@pytest.fixture
def example(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    staging = tmp_path / "interim"
    reference = tmp_path / "reference"
    staging.mkdir()
    reference.mkdir()

    pd.DataFrame(
        [
            ("E1", 100, 70, 70.0),
            ("E2", 100, 90, 90.0),
            ("E3", 100, 85, 85.0),
        ],
        columns=["source_region_code", "electors", "voters", "reported_turnout"],
    ).to_csv(staging / "election.csv", index=False)

    rows = []
    for code, values in [
        ("P1", [10, 20, 15, 5]),
        ("P2", [10, 20, 10, 5]),
        ("P3", [5, 30, 20, 10]),
    ]:
        rows.extend((code, age, value) for age, value in zip([0, 18, 65, 80], values))
    pd.DataFrame(rows, columns=["source_region_code", "age", "population"]).to_csv(
        staging / "population.csv", index=False
    )

    pd.DataFrame(
        [("F1", 35), ("F2", 20)],
        columns=["source_region_code", "fiscal_independence"],
    ).to_csv(staging / "fiscal.csv", index=False)

    pd.DataFrame(
        [("M1", 3, 1000), ("M2", -1, 500), ("M3", 10, 2000)],
        columns=["source_region_code", "net_migrants", "midyear_population"],
    ).to_csv(staging / "migration.csv", index=False)

    mapping = []
    sources = {
        "election": [("E1", "R1"), ("E2", "R1"), ("E3", "R2")],
        "population": [("P1", "R1"), ("P2", "R1"), ("P3", "R2")],
        "fiscal": [("F1", "R1"), ("F2", "R2")],
        "migration": [("M1", "R1"), ("M2", "R1"), ("M3", "R2")],
    }
    for dataset, pairs in sources.items():
        for src, region in pairs:
            mapping.append(
                (
                    dataset,
                    src,
                    region,
                    "가상시" if region == "R1" else "가상군",
                    "가상도",
                    "시" if region == "R1" else "군",
                )
            )
    crosswalk = reference / "region_crosswalk.csv"
    pd.DataFrame(
        mapping,
        columns=[
            "dataset",
            "source_region_code",
            "region_code",
            "region_name",
            "province",
            "region_type",
        ],
    ).to_csv(crosswalk, index=False)
    return staging, crosswalk, tmp_path / "processed.csv", tmp_path / "quality.json"


def test_counts_are_aggregated_before_rates(example: tuple[Path, Path, Path, Path]) -> None:
    staging, crosswalk, output, report = example
    results = build_dataset(staging, crosswalk, output, report).set_index("region_code")
    assert len(results) == 2
    assert results.loc["R1", "electors"] == 200
    assert results.loc["R1", "voters"] == 160
    assert results.loc["R1", "turnout"] == pytest.approx(80)
    assert results.loc["R1", "population_65plus"] == 35
    assert results.loc["R1", "population_18plus"] == 75
    assert results.loc["R1", "population_80plus"] == 10
    assert results.loc["R1", "aging_rate"] == pytest.approx(100 * 35 / 75)
    assert results.loc["R1", "oldest_share"] == pytest.approx(100 * 10 / 35)
    assert results.loc["R1", "net_migration_rate"] == pytest.approx(100 * 2 / 1500)
    assert output.exists()
    assert '"official_election_totals_verified": false' in report.read_text(encoding="utf-8")


def test_unmapped_region_is_rejected(example: tuple[Path, Path, Path, Path]) -> None:
    staging, crosswalk, output, report = example
    mapping = pd.read_csv(crosswalk)
    mapping = mapping.loc[
        ~((mapping["dataset"] == "election") & (mapping["source_region_code"] == "E3"))
    ]
    mapping.to_csv(crosswalk, index=False)
    with pytest.raises(ValueError, match="대응되지 않은"):
        build_dataset(staging, crosswalk, output, report)


def test_fiscal_percentages_are_not_aggregated(
    example: tuple[Path, Path, Path, Path],
) -> None:
    staging, crosswalk, output, report = example
    mapping = pd.read_csv(crosswalk)
    extra = mapping.loc[
        (mapping["dataset"] == "fiscal") & (mapping["source_region_code"] == "F1")
    ].copy()
    extra["source_region_code"] = "F1b"
    mapping = pd.concat([mapping, extra], ignore_index=True)
    mapping.to_csv(crosswalk, index=False)

    fiscal = pd.read_csv(staging / "fiscal.csv")
    fiscal = pd.concat(
        [fiscal, pd.DataFrame([{"source_region_code": "F1b", "fiscal_independence": 50}])],
        ignore_index=True,
    )
    fiscal.to_csv(staging / "fiscal.csv", index=False)
    with pytest.raises(ValueError, match="비율 합산 금지"):
        build_dataset(staging, crosswalk, output, report)


def test_duplicate_election_rows_fail(example: tuple[Path, Path, Path, Path]) -> None:
    staging, crosswalk, output, report = example
    election = pd.read_csv(staging / "election.csv")
    election = pd.concat([election, election.head(1)], ignore_index=True)
    election.to_csv(staging / "election.csv", index=False)
    with pytest.raises(ValueError, match="원본 지역코드 중복"):
        build_dataset(staging, crosswalk, output, report)


def test_crosswalk_conflicting_metadata_fail(
    example: tuple[Path, Path, Path, Path],
) -> None:
    staging, crosswalk, output, report = example
    mapping = pd.read_csv(crosswalk)
    mapping.loc[
        (mapping["dataset"] == "population") & (mapping["source_region_code"] == "P1"),
        "region_name",
    ] = "다른가상시"
    mapping.to_csv(crosswalk, index=False)
    with pytest.raises(ValueError, match="상충"):
        build_dataset(staging, crosswalk, output, report)


@pytest.mark.parametrize("value", ["invalid", "NA", "NaN", "null", "inf", "-inf", "-1", "101"])
def test_invalid_reported_turnout_is_rejected(example, value) -> None:
    staging, crosswalk, output, report = example
    election = pd.read_csv(staging / "election.csv", dtype=str)
    election.loc[0, "reported_turnout"] = value
    election.to_csv(staging / "election.csv", index=False)
    with pytest.raises(ValueError, match="reported_turnout"):
        build_dataset(staging, crosswalk, output, report)
    assert not output.exists()
    assert not report.exists()


@pytest.mark.parametrize("value", [None, "", "   ", "70.0"])
def test_optional_reported_turnout_accepts_blank_or_valid(example, value) -> None:
    staging, crosswalk, output, report = example
    election = pd.read_csv(staging / "election.csv", dtype=str)
    election.loc[0, "reported_turnout"] = value
    election.to_csv(staging / "election.csv", index=False)
    result = build_dataset(staging, crosswalk, output, report).set_index("region_code")
    assert result.loc["R1", "turnout"] == pytest.approx(80)


def test_reported_turnout_column_is_optional(example) -> None:
    staging, crosswalk, output, report = example
    election = pd.read_csv(staging / "election.csv").drop(columns="reported_turnout")
    election.to_csv(staging / "election.csv", index=False)
    result = build_dataset(staging, crosswalk, output, report).set_index("region_code")
    assert result.loc["R1", "turnout"] == pytest.approx(80)


def test_missing_fiscal_row_preserves_core_region(example) -> None:
    staging, crosswalk, output, report = example
    fiscal = pd.read_csv(staging / "fiscal.csv")
    fiscal.iloc[:1].to_csv(staging / "fiscal.csv", index=False)
    result = build_dataset(staging, crosswalk, output, report).set_index("region_code")
    assert set(result.index) == {"R1", "R2"}
    assert pd.isna(result.loc["R2", "fiscal_independence"])


def test_same_region_missing_from_both_core_inputs_rejected(example):
    staging, crosswalk, output, report = example
    for dataset, code in [("election", "E3"), ("population", "P3")]:
        path = staging / f"{dataset}.csv"
        frame = pd.read_csv(path)
        frame.loc[frame.source_region_code != code].to_csv(path, index=False)
    with pytest.raises(ValueError, match="지역 누락"):
        build_dataset(*example)
    assert not output.exists()


def test_missing_election_subunit_rejected_even_when_city_remains(example):
    staging, crosswalk, output, report = example
    frame = pd.read_csv(staging / "election.csv")
    frame.loc[frame.source_region_code != "E2"].to_csv(staging / "election.csv", index=False)
    with pytest.raises(ValueError, match="지역 누락"):
        build_dataset(*example)


@pytest.mark.parametrize("value", [70.04, 70.1])
def test_reported_turnout_uses_one_decimal_contract(example, value):
    staging, crosswalk, output, report = example
    frame = pd.read_csv(staging / "election.csv")
    frame.loc[0, "reported_turnout"] = value
    frame.to_csv(staging / "election.csv", index=False)
    with pytest.raises(ValueError):
        build_dataset(*example)


@pytest.fixture
def strict_example(example):
    """입력 증거용 인공 fixture. 공식 수치 검증으로 취급하지 않는다."""
    import hashlib
    import json

    staging, crosswalk, output, report = example
    raw = staging.parent / "raw"
    raw.mkdir()
    reports = staging.parent / "outputs"
    reports.mkdir()
    expected = crosswalk.parent / "expected_regions.csv"
    mapping = pd.read_csv(crosswalk, dtype=str)
    mapping[["region_code", "region_name", "province", "region_type"]].drop_duplicates().to_csv(
        expected, index=False
    )
    for dataset in ["election", "population", "fiscal", "migration"]:
        source = raw / f"{dataset}_raw.txt"
        source.write_text(f"synthetic {dataset} source")
        evidence = {
            "status": f"{dataset}_staging_internal_checks_passed",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "crosswalk_sha256": hashlib.sha256(crosswalk.read_bytes()).hexdigest(),
            "output_sha256": hashlib.sha256((staging / f"{dataset}.csv").read_bytes()).hexdigest(),
        }
        if dataset == "population":
            evidence["expected_ages"] = [0, 18, 65, 80]
        if dataset == "fiscal":
            definition = raw / "definition.txt"
            definition.write_text("synthetic definition")
            evidence["definition_sha256"] = hashlib.sha256(definition.read_bytes()).hexdigest()
        if dataset == "migration":
            midyear = raw / "midyear.txt"
            midyear.write_text("synthetic midyear source")
            evidence["midyear_source_sha256"] = hashlib.sha256(midyear.read_bytes()).hexdigest()
        (reports / f"{dataset}_staging_checks.json").write_text(json.dumps(evidence))
    mapping_evidence = {
        "status": "region_reference_structure_verified",
        "hashes": {
            str(path.relative_to(staging.parent.parent)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in [expected, crosswalk]
        },
    }
    (reports / "region_mapping_checks.json").write_text(json.dumps(mapping_evidence))
    return example, expected, reports


def test_strict_input_contract_does_not_claim_official_verification(strict_example):
    import json

    paths, expected, reports = strict_example
    build_dataset(*paths, expected_regions_path=expected, staging_reports_dir=reports)
    quality = json.loads(paths[-1].read_text())
    assert quality["input_contract_verified"]
    assert quality["population_age_coverage_verified"]
    assert not quality["official_election_totals_verified"]


@pytest.mark.parametrize("all_regions", [False, True])
def test_declared_age_missing_rejected_even_if_input_hash_updated(strict_example, all_regions):
    import hashlib
    import json

    paths, expected, reports = strict_example
    path = paths[0] / "population.csv"
    frame = pd.read_csv(path)
    keep = (
        frame.age.ne(18) if all_regions else ~(frame.age.eq(18) & frame.source_region_code.eq("P1"))
    )
    frame.loc[keep].to_csv(path, index=False)
    evidence_path = reports / "population_staging_checks.json"
    evidence = json.loads(evidence_path.read_text())
    evidence["output_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence_path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match="연령 구간"):
        build_dataset(*paths, expected_regions_path=expected, staging_reports_dir=reports)
    assert not paths[2].exists()


@pytest.mark.parametrize("target", ["input", "source", "crosswalk", "expected"])
def test_strict_changed_evidence_rejected(strict_example, target):
    paths, expected, reports = strict_example
    changed = {
        "input": paths[0] / "election.csv",
        "source": paths[0].parent / "raw/election_raw.txt",
        "crosswalk": paths[1],
        "expected": expected,
    }[target]
    with changed.open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="해시"):
        build_dataset(*paths, expected_regions_path=expected, staging_reports_dir=reports)
    assert not paths[2].exists()


def test_source_change_invalidates_existing_true_certificate(tmp_path):
    import hashlib
    import json

    from political_analysis.pipeline import verify_dataset_certificate

    source = tmp_path / "raw.txt"
    source.write_text("original")
    data = tmp_path / "data.csv"
    data.write_text("a,b\n1,2\n")
    quality = tmp_path / "quality.json"
    quality.write_text(
        json.dumps(
            {
                "input_contract_verified": True,
                "official_election_totals_verified": True,
                "dataset_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
                "verified_files": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()},
            }
        )
    )
    verify_dataset_certificate(data, quality)
    source.write_text("changed")
    with pytest.raises(ValueError, match="해시"):
        verify_dataset_certificate(data, quality)


def test_unverified_certificate_rejected(example):
    from political_analysis.pipeline import verify_dataset_certificate

    build_dataset(*example)
    with pytest.raises(ValueError, match="미완료"):
        verify_dataset_certificate(example[2], example[3])


def test_independent_expected_region_not_derived_from_inputs(strict_example):
    paths, expected, reports = strict_example
    frame = pd.read_csv(expected)
    extra = frame.iloc[0].copy()
    extra["region_code"] = "R3"
    extra["region_name"] = "추가군"
    pd.concat([frame, extra.to_frame().T], ignore_index=True).to_csv(expected, index=False)
    with pytest.raises(ValueError, match="독립 기대 지역"):
        build_dataset(*paths, expected_regions_path=expected, staging_reports_dir=reports)


@pytest.mark.parametrize("mutation", ["duplicate", "unexpected"])
def test_population_long_age_contract_rejects_duplicate_or_extra(strict_example, mutation):
    import hashlib
    import json

    paths, expected, reports = strict_example
    path = paths[0] / "population.csv"
    frame = pd.read_csv(path)
    if mutation == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    else:
        frame.loc[0, "age"] = 1
    frame.to_csv(path, index=False)
    evidence_path = reports / "population_staging_checks.json"
    evidence = json.loads(evidence_path.read_text())
    evidence["output_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence_path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match="중복|연령 구간"):
        build_dataset(*paths, expected_regions_path=expected, staging_reports_dir=reports)


def test_positive_half_person_denominator_allowed(example):
    path = example[0] / "migration.csv"
    frame = pd.read_csv(path)
    frame["midyear_population"] = frame["midyear_population"].astype(float)
    frame.loc[2, "midyear_population"] = 0.5
    frame.to_csv(path, index=False)
    result = build_dataset(*example).set_index("region_code")
    assert result.loc["R2", "midyear_population"] == 0.5
