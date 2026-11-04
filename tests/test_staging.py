"""원본 형태의 인공 예제로 스테이징 계수·중복·범위 보존을 검사한다."""

from pathlib import Path

import pandas as pd
import pytest

from political_analysis.staging import stage_election


@pytest.fixture
def election_source(tmp_path: Path):
    source = tmp_path / "raw.csv"
    rows = []
    for district, electors, voters in [("가시동구", 100, 70), ("가시서구", 200, 150)]:
        for item, count in [("선거인수", electors), ("투표수", voters)]:
            rows.append(("가도", district, "가동", "제1투표구", item, str(count)))
    pd.DataFrame(
        rows, columns=["시도명", "구시군명", "읍면동명", "투표구명", "후보자", "득표수"]
    ).to_csv(source, index=False, encoding="utf-8-sig")
    crosswalk = tmp_path / "crosswalk.csv"
    pd.DataFrame(
        {
            "dataset": ["election", "election"],
            "source_region_code": ["가도|가시동구", "가도|가시서구"],
            "region_code": ["001", "001"],
        }
    ).to_csv(crosswalk, index=False)
    return source, crosswalk, tmp_path / "election.csv", tmp_path / "checks.json"


def test_election_counts_and_source_keys_preserved(election_source):
    result = stage_election(*election_source).set_index("source_region_code")
    assert set(result.index) == {"가도|가시동구", "가도|가시서구"}
    assert result.electors.sum() == 300
    assert result.voters.sum() == 220
    assert result.loc["가도|가시서구", "voters"] == 150


@pytest.mark.parametrize(
    "mutation", ["duplicate_count", "unmapped", "missing_region", "parent_total"]
)
def test_election_invalid_scope_fails_without_outputs(election_source, mutation):
    source, crosswalk, output, report = election_source
    frame = pd.read_csv(source, dtype=str, keep_default_na=False)
    if mutation == "duplicate_count":
        frame = pd.concat([frame, frame.head(1)], ignore_index=True)
    elif mutation == "unmapped":
        frame.loc[0, "구시군명"] = "없는시"
    elif mutation == "missing_region":
        frame = frame.loc[frame["구시군명"] != "가시서구"]
    else:
        frame.loc[:1, "읍면동명"] = "합계"
        frame.loc[:1, "투표구명"] = ""
    frame.to_csv(source, index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError):
        stage_election(source, crosswalk, output, report)
    assert not output.exists()
    assert not report.exists()


@pytest.fixture
def population_source(tmp_path: Path):
    source = tmp_path / "population_raw.csv"
    prefix = "2025년05월_계_"
    ages = [f"{prefix}{age}세" for age in range(100)] + [f"{prefix}100세 이상"]
    rows = []
    values = [
        {17: 3, 18: 5, 64: 7, 65: 11, 79: 13, 80: 17, 100: 19},
        {0: 1000, 18: 10, 65: 20, 100: 5},
        {0: 500},
    ]
    for label, counts in zip(
        ["가도 가시 (0101000000)", "가도 나시 (0102000000)", "가도 (0100000000)"], values
    ):
        total = sum(counts.values())
        rows.append(
            [label, str(total), str(total)] + [f"{counts.get(age, 0):,}" for age in range(101)]
        )
    columns = ["행정구역", prefix + "총인구수", prefix + "연령구간인구수"] + ages
    pd.DataFrame(rows, columns=columns).to_csv(source, index=False, encoding="cp949")
    crosswalk = tmp_path / "crosswalk.csv"
    pd.DataFrame(
        {
            "dataset": ["population"] * 2,
            "source_region_code": ["0101000000", "0102000000"],
            "region_code": ["0101000000", "0102000000"],
        }
    ).to_csv(crosswalk, index=False)
    inventory = tmp_path / "inventory.csv"
    pd.DataFrame(
        {
            "dataset": ["population"] * 3,
            "source_region_code": ["0101000000", "0102000000", "0100000000"],
            "region_code": ["0101000000", "0102000000", ""],
            "disposition": ["municipality", "municipality", "exclude_province_total"],
        }
    ).to_csv(inventory, index=False)
    return (
        source,
        crosswalk,
        inventory,
        tmp_path / "population.csv",
        tmp_path / "checks.json",
        tmp_path / "checks.csv",
    )


def test_population_age_boundaries_totals_and_zero_preserved(population_source):
    from political_analysis.staging import stage_population

    result = stage_population(*population_source)
    first = result.loc[result.source_region_code == "0101000000"]
    assert len(result) == 202
    assert set(first.age) == set(range(101))
    assert first.population.sum() == 75
    assert first.loc[first.age >= 18, "population"].sum() == 72
    assert first.loc[first.age >= 65, "population"].sum() == 60
    assert first.loc[first.age >= 80, "population"].sum() == 36
    assert first.loc[first.age == 15, "population"].item() == 0
    assert set(result.source_region_code) == {"0101000000", "0102000000"}
    checks = pd.read_csv(population_source[-1])
    assert set(checks.population_total) == {75, 1035}


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_age",
        "extra_open_age",
        "duplicate_header",
        "missing_region",
        "duplicate_region",
        "unreviewed_region",
        "total_mismatch",
        "interval_mismatch",
        "blank_count",
        "fractional_count",
        "negative_count",
        "infinite_count",
        "duplicate_crosswalk",
        "crosswalk_inventory_mismatch",
    ],
)
def test_population_invalid_source_rejected(population_source, mutation):
    import csv

    from political_analysis.staging import stage_population

    source, crosswalk, inventory, output, report, checks = population_source
    frame = pd.read_csv(source, encoding="cp949", dtype=str, keep_default_na=False)
    age = "2025년05월_계_18세"
    if mutation == "missing_age":
        frame = frame.drop(columns=age)
    elif mutation == "extra_open_age":
        frame["2025년05월_계_100세"] = "0"
    elif mutation == "missing_region":
        frame = frame.iloc[1:]
    elif mutation == "duplicate_region":
        frame = pd.concat([frame, frame.head(1)], ignore_index=True)
    elif mutation == "unreviewed_region":
        frame.loc[2, "행정구역"] = "가도 없는시 (0103000000)"
    elif mutation == "total_mismatch":
        frame.loc[0, "2025년05월_계_총인구수"] = "76"
    elif mutation == "interval_mismatch":
        frame.loc[0, "2025년05월_계_연령구간인구수"] = "76"
    elif mutation.endswith("_count"):
        frame.loc[0, age] = {
            "blank_count": "",
            "fractional_count": "5.5",
            "negative_count": "-1",
            "infinite_count": "inf",
        }[mutation]
    elif mutation in ["duplicate_crosswalk", "crosswalk_inventory_mismatch"]:
        mapping = pd.read_csv(crosswalk, dtype=str)
        mapping = (
            pd.concat([mapping, mapping.head(1)], ignore_index=True)
            if mutation == "duplicate_crosswalk"
            else mapping.iloc[1:]
        )
        mapping.to_csv(crosswalk, index=False)
    frame.to_csv(source, index=False, encoding="cp949")
    if mutation == "duplicate_header":
        with source.open(encoding="cp949", newline="") as f:
            rows = list(csv.reader(f))
        rows[0].append(age)
        for row in rows[1:]:
            row.append("0")
        with source.open("w", encoding="cp949", newline="") as f:
            csv.writer(f).writerows(rows)
    with pytest.raises(ValueError):
        stage_population(source, crosswalk, inventory, output, report, checks)
    assert not output.exists()
    assert not report.exists()
    assert not checks.exists()


@pytest.fixture
def fiscal_source(tmp_path: Path):
    import json

    source = tmp_path / "fiscal_raw.json"
    rows = [
        {"fyr": "", "lafNm": "가도가시", "firRt": "12.34"},
        {"fyr": "", "lafNm": "세종본청", "firRt": "54.31"},
        {"fyr": "", "lafNm": "가도본청", "firRt": "50"},
    ]
    source.write_text(json.dumps({"firFrsIxInqRsltDto": rows}, ensure_ascii=False))
    crosswalk = tmp_path / "crosswalk.csv"
    pd.DataFrame(
        {
            "dataset": ["fiscal"] * 2,
            "source_region_code": ["가도가시", "세종본청"],
            "region_code": ["0101000000", "3600000000"],
        }
    ).to_csv(crosswalk, index=False)
    inventory = tmp_path / "inventory.csv"
    pd.DataFrame(
        {
            "dataset": ["fiscal"] * 3,
            "source_region_code": ["가도가시", "세종본청", "가도본청"],
            "region_code": ["0101000000", "3600000000", ""],
            "disposition": ["municipality", "special_province", "exclude_province_total"],
        }
    ).to_csv(inventory, index=False)
    definition = tmp_path / "definition.json"
    definition.write_text(
        json.dumps(
            {
                "byatcSituPbaIndcInfoInqRsltDto": {
                    "fyr": "2025",
                    "menuDtsEplCn": "재정자립도[당초](개편후) 산정기준:예산, 당초 "
                    "대상회계:일반회계 기준연도:2025",
                }
            },
            ensure_ascii=False,
        )
    )
    return (
        source,
        crosswalk,
        inventory,
        definition,
        tmp_path / "fiscal.csv",
        tmp_path / "checks.json",
        tmp_path / "checks.csv",
    )


def test_fiscal_values_and_special_region_preserved(fiscal_source):
    from political_analysis.staging import stage_fiscal

    result = stage_fiscal(*fiscal_source).set_index("source_region_code")
    assert result.fiscal_independence.to_dict() == {"가도가시": 12.34, "세종본청": 54.31}
    assert set(pd.read_csv(fiscal_source[-1], dtype=str).region_code) == {
        "0101000000",
        "3600000000",
    }


@pytest.mark.parametrize("missing", [None, "", "  ", "-"])
def test_fiscal_missing_value_omitted_but_reported(fiscal_source, missing):
    import json

    from political_analysis.staging import stage_fiscal

    source, crosswalk, inventory, definition, output, report, checks = fiscal_source
    data = json.loads(source.read_text())
    data["firFrsIxInqRsltDto"][0]["firRt"] = missing
    source.write_text(json.dumps(data, ensure_ascii=False))
    result = stage_fiscal(*fiscal_source)
    assert result.source_region_code.tolist() == ["세종본청"]
    audit = pd.read_csv(checks, keep_default_na=False).set_index("source_region_code")
    assert audit.loc["가도가시", "status"] == "missing_source_value"
    assert audit.loc["가도가시", "fiscal_independence"] == ""
    assert json.loads(report.read_text())["missing_regions"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_source",
        "missing_region",
        "unreviewed_region",
        "duplicate_target",
        "duplicate_crosswalk",
        "inventory_mismatch",
        "wrong_year",
        "wrong_basis",
        "wrong_indicator",
        "wrong_record_year",
        "invalid_text",
        "negative",
        "over_100",
        "infinite",
    ],
)
def test_fiscal_invalid_source_rejected(fiscal_source, mutation):
    import json

    from political_analysis.staging import stage_fiscal

    source, crosswalk, inventory, definition, output, report, checks = fiscal_source
    data = json.loads(source.read_text())
    rows = data["firFrsIxInqRsltDto"]
    if mutation == "duplicate_source":
        rows.append(rows[0].copy())
    elif mutation == "missing_region":
        del rows[0]
    elif mutation == "unreviewed_region":
        rows[2]["lafNm"] = "모르는기관"
    elif mutation in ["duplicate_target", "duplicate_crosswalk", "inventory_mismatch"]:
        mapping = pd.read_csv(crosswalk, dtype=str)
        if mutation == "duplicate_target":
            mapping.loc[1, "region_code"] = mapping.loc[0, "region_code"]
        elif mutation == "duplicate_crosswalk":
            mapping = pd.concat([mapping, mapping.head(1)], ignore_index=True)
        else:
            mapping = mapping.iloc[1:]
        mapping.to_csv(crosswalk, index=False)
    elif mutation.startswith("wrong_") and mutation != "wrong_record_year":
        meta = json.loads(definition.read_text())
        spec = meta["byatcSituPbaIndcInfoInqRsltDto"]
        if mutation == "wrong_year":
            spec["fyr"] = "2024"
        else:
            spec["menuDtsEplCn"] = spec["menuDtsEplCn"].replace(
                "당초" if mutation == "wrong_basis" else "개편후",
                "최종" if mutation == "wrong_basis" else "개편전",
            )
        definition.write_text(json.dumps(meta, ensure_ascii=False))
    elif mutation == "wrong_record_year":
        rows[0]["fyr"] = "2024"
    else:
        rows[0]["firRt"] = {
            "invalid_text": "NA",
            "negative": "-1",
            "over_100": "100.1",
            "infinite": "inf",
        }[mutation]
    source.write_text(json.dumps(data, ensure_ascii=False))
    with pytest.raises(ValueError):
        stage_fiscal(*fiscal_source)
    assert not output.exists()
    assert not report.exists()
    assert not checks.exists()


@pytest.mark.parametrize("value", ["0", "100"])
def test_fiscal_zero_and_hundred_are_observed_values(fiscal_source, value):
    import json

    from political_analysis.staging import stage_fiscal

    source = fiscal_source[0]
    data = json.loads(source.read_text())
    data["firFrsIxInqRsltDto"][0]["firRt"] = value
    source.write_text(json.dumps(data, ensure_ascii=False))
    result = stage_fiscal(*fiscal_source).set_index("source_region_code")
    assert len(result) == 2
    assert result.loc["가도가시", "fiscal_independence"] == float(value)
    audit = pd.read_csv(fiscal_source[-1]).set_index("source_region_code")
    assert audit.loc["가도가시", "status"] == "observed"


@pytest.fixture
def migration_source(tmp_path: Path):
    import csv

    source = tmp_path / "migration_raw.csv"
    with source.open("w", encoding="cp949", newline="") as f:
        csv.writer(f).writerows(
            [
                ["A 행정구역(시군구)별"] + ["Y2024 2024"] * 8,
                ["A 행정구역(시군구)별"]
                + [
                    x + " 항목 (명)"
                    for x in ["T10", "T20", "T25", "T30", "T31", "T32", "T40", "T50"]
                ],
                ["01010 가시", "10", "15", "-5", "0", "0", "0", "10", "15"],
                ["01020 나시", "8", "8", "0", "0", "0", "0", "8", "8"],
                ["01 가도", "18", "23", "-5", "0", "0", "0", "18", "23"],
            ]
        )
    midyear = tmp_path / "midyear_raw.csv"
    with midyear.open("w", encoding="cp949", newline="") as f:
        csv.writer(f).writerows(
            [
                ["A 행정구역(시군구)별", "SBB 성별", "YRE 연령별", "Y2024 2024"],
                ["10102 나시", "0 계", "000 계", "250"],
                ["10101 가시", "0 계", "000 계", "125.5"],
                ["10 가도", "0 계", "000 계", "375.5"],
            ]
        )
    crosswalk = tmp_path / "crosswalk.csv"
    pd.DataFrame(
        {
            "dataset": ["migration"] * 2,
            "source_region_code": ["01010", "01020"],
            "region_code": ["0101000000", "0102000000"],
        }
    ).to_csv(crosswalk, index=False)
    inventory = tmp_path / "inventory.csv"
    pd.DataFrame(
        {
            "dataset": ["migration"] * 3,
            "source_region_code": ["01010", "01020", "01"],
            "region_code": ["0101000000", "0102000000", ""],
            "disposition": ["municipality", "municipality", "exclude_province_total"],
        }
    ).to_csv(inventory, index=False)
    midmap = tmp_path / "midmap.csv"
    pd.DataFrame(
        {
            "source_region_code": ["10101", "10102", "10"],
            "region_code": ["0101000000", "0102000000", ""],
            "disposition": ["municipality", "municipality", "exclude_province_total"],
        }
    ).to_csv(midmap, index=False)
    return (
        source,
        midyear,
        crosswalk,
        inventory,
        midmap,
        tmp_path / "migration.csv",
        tmp_path / "checks.json",
        tmp_path / "checks.csv",
    )


def test_migration_signed_counts_half_population_and_keyed_join(migration_source):
    from political_analysis.staging import stage_migration

    result = stage_migration(*migration_source).set_index("source_region_code")
    assert len(result) == 2
    assert result.loc["01010", "net_migrants"] == -5
    assert result.loc["01020", "net_migrants"] == 0
    assert result.loc["01010", "midyear_population"] == 125.5
    audit = pd.read_csv(migration_source[-1], dtype={"source_region_code": str}).set_index(
        "source_region_code"
    )
    assert audit.loc["01010", "net_migration_rate"] == pytest.approx(-500 / 125.5)
    assert audit.loc["01020", "net_migration_rate"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_source",
        "missing_source",
        "unknown_source",
        "duplicate_midyear",
        "missing_midyear",
        "unknown_midyear",
        "wrong_year",
        "wrong_midyear_year",
        "wrong_sex",
        "wrong_age",
        "duplicate_target",
        "duplicate_midyear_target",
        "midyear_target_mismatch",
        "reference_mismatch",
        "fractional_net",
        "infinite_net",
        "net_mismatch",
        "negative_inflow",
        "zero_denominator",
        "negative_denominator",
        "infinite_denominator",
        "missing_denominator",
    ],
)
def test_migration_invalid_inputs_rejected(migration_source, mutation):
    import csv

    from political_analysis.staging import stage_migration

    source, midyear, crosswalk, inventory, midmap, output, report, checks = migration_source
    with source.open(encoding="cp949", newline="") as f:
        rows = list(csv.reader(f))
    with midyear.open(encoding="cp949", newline="") as f:
        population = list(csv.reader(f))
    if mutation == "duplicate_source":
        rows.append(rows[2].copy())
    elif mutation == "missing_source":
        del rows[2]
    elif mutation == "unknown_source":
        rows[2][0] = "99999 모르는시"
    elif mutation == "duplicate_midyear":
        population.append(population[1].copy())
    elif mutation == "missing_midyear":
        del population[1]
    elif mutation == "unknown_midyear":
        population[1][0] = "99999 모르는시"
    elif mutation == "wrong_year":
        rows[0][1] = "Y2025 2025"
    elif mutation == "wrong_midyear_year":
        population[0][-1] = "Y2025 2025"
    elif mutation == "wrong_sex":
        population[1][1] = "1 남자"
    elif mutation == "wrong_age":
        population[1][2] = "020 20세"
    elif mutation in ["duplicate_target", "reference_mismatch"]:
        mapping = pd.read_csv(crosswalk, dtype=str)
        if mutation == "duplicate_target":
            mapping.loc[1, "region_code"] = mapping.loc[0, "region_code"]
        else:
            mapping = mapping.iloc[1:]
        mapping.to_csv(crosswalk, index=False)
    elif mutation in ["duplicate_midyear_target", "midyear_target_mismatch"]:
        mapping = pd.read_csv(midmap, dtype=str, keep_default_na=False)
        mapping.loc[1, "region_code"] = (
            mapping.loc[0, "region_code"] if mutation == "duplicate_midyear_target" else "999"
        )
        mapping.to_csv(midmap, index=False)
    elif mutation in ["fractional_net", "infinite_net", "net_mismatch"]:
        rows[2][3] = {"fractional_net": "-5.5", "infinite_net": "inf", "net_mismatch": "-6"}[
            mutation
        ]
    elif mutation == "negative_inflow":
        rows[2][1] = "-10"
    else:
        population[1][-1] = {
            "zero_denominator": "0",
            "negative_denominator": "-1",
            "infinite_denominator": "inf",
            "missing_denominator": "",
        }[mutation]
    for path, data in [(source, rows), (midyear, population)]:
        with path.open("w", encoding="cp949", newline="") as f:
            csv.writer(f).writerows(data)
    with pytest.raises(ValueError):
        stage_migration(*migration_source)
    assert not output.exists()
    assert not report.exists()
    assert not checks.exists()
