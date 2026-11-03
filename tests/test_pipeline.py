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
                (dataset, src, region, "가상시" if region == "R1" else "가상군",
                 "가상도", "시" if region == "R1" else "군")
            )
    crosswalk = reference / "region_crosswalk.csv"
    pd.DataFrame(
        mapping,
        columns=[
            "dataset", "source_region_code", "region_code",
            "region_name", "province", "region_type",
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
