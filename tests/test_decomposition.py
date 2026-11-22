"""분해 분석은 손으로 계산 가능한 인공 자료로만 검사한다. 실제 연구 결과가 아니다."""

import hashlib
import io
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from political_analysis import decomposition, pipeline
from political_analysis.decomposition import (
    AGE_MEMBER,
    BAND_COLUMNS,
    BANDS,
    build_region_frame,
    composition_expected,
    fit_components,
    gap_summary,
    national_rates,
    population_bands,
    population_weighted_rates,
    province_table,
    read_age_table,
    run_decomposition,
    sensitivity_table,
    sign_checks,
)


def _sheet_xml(rows):
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = ET.Element("worksheet", xmlns=namespace)
    body = ET.SubElement(sheet, "sheetData")
    for index, cells in enumerate(rows, start=1):
        row = ET.SubElement(body, "row", r=str(index))
        for column, value in cells.items():
            cell = ET.SubElement(row, "c", r=f"{column}{index}", t="inlineStr")
            ET.SubElement(ET.SubElement(cell, "is"), "t").text = str(value)
    return ET.tostring(sheet)


def _workbook(sheets):
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relation = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    workbook = ET.Element("workbook", xmlns=namespace)
    group = ET.SubElement(workbook, "sheets")
    relations = ["<Relationships>"]
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        for number, (name, rows) in enumerate(sheets.items(), start=1):
            ET.SubElement(group, "sheet", name=name, attrib={relation: f"rId{number}"})
            relations.append(f'<Relationship Id="rId{number}" Target="worksheets/s{number}.xml"/>')
            archive.writestr(f"xl/worksheets/s{number}.xml", _sheet_xml(rows))
        relations.append("</Relationships>")
        archive.writestr("xl/workbook.xml", ET.tostring(workbook))
        archive.writestr("xl/_rels/workbook.xml.rels", "".join(relations))
    return output.getvalue()


def _unit_rows(unit, electors, voters):
    columns = list(BAND_COLUMNS)
    def cells(values):
        data = {column: f"{value:,}" for column, value in zip(columns, values)}
        data["D"] = f"{sum(values):,}"
        return data
    return [
        {"A": unit, "B": "합계", "C": "선거인수", **cells(electors)},
        {"C": "투표자수", **cells(voters)},
        {"C": "투표율", "D": "0.0"},
    ]


def _sheet_rows_for(province, units):
    rows = [
        {"A": "제목"},
        {},
        {"A": f"[표본][{province}]"},
        {"A": "구분", "D": "합계", **BAND_COLUMNS},
    ]
    size = len(BANDS)
    total_e = [sum(unit[1][i] for unit in units) for i in range(size)]
    total_v = [sum(unit[2][i] for unit in units) for i in range(size)]
    rows += _unit_rows("전체", total_e, total_v)
    for unit in units:
        rows += _unit_rows(*unit)
    return rows


def _bands(value_18, value_70s, value_80):
    values = [value_18] * 9 + [value_70s, value_80]
    return values


@pytest.fixture
def age_case(tmp_path, monkeypatch):
    monkeypatch.setattr(decomposition, "AGE_SHEETS", ("가", "나"))
    sheets = {
        "가": [
            ("가시동구", _bands(10, 100, 50), _bands(8, 90, 30)),
            ("가시서구", _bands(10, 100, 50), _bands(6, 80, 20)),
        ],
        "나": [("나군", _bands(20, 200, 100), _bands(10, 170, 60))],
    }
    crosswalk = pd.DataFrame(
        {
            "dataset": ["election"] * 3,
            "source_region_code": ["가도|가시동구", "가도|가시서구", "나도|나군"],
            "region_code": ["R1", "R1", "R2"],
        }
    )
    return tmp_path / "official.zip", crosswalk, sheets


def _write_zip(path, sheets, provinces=None):
    provinces = provinces or {"가": "가도", "나": "나도"}
    payload = {name: _sheet_rows_for(provinces[name], units) for name, units in sheets.items()}
    with ZipFile(path, "w") as archive:
        archive.writestr(AGE_MEMBER, _workbook(payload))
    return payload


def test_units_are_summed_into_research_regions(age_case):
    path, crosswalk, sheets = age_case
    _write_zip(path, sheets)
    table = read_age_table(path, crosswalk)
    assert table.loc["R1", "e_70-79"] == 200
    assert table.loc["R1", "v_70-79"] == 170
    assert table.loc["R1", "v_80+"] == 50
    assert table.loc["R2", "e_80+"] == 100


@pytest.mark.parametrize(
    "mutation",
    [
        "band_sum",
        "voter_band_sum",
        "unit_total",
        "unknown_unit",
        "missing_unit",
        "duplicate_unit",
        "voters_over_electors",
        "missing_sheet",
        "header",
        "text_cell",
        "blank_cell",
        "no_province_title",
    ],
)
def test_broken_age_table_is_rejected(age_case, mutation):
    path, crosswalk, sheets = age_case
    payload = {
        "가": _sheet_rows_for("가도", sheets["가"]),
        "나": _sheet_rows_for("나도", sheets["나"]),
    }
    first_unit = 7
    if mutation == "band_sum":
        payload["가"][first_unit]["E"] = "11"
    elif mutation == "voter_band_sum":
        payload["가"][first_unit + 1]["E"] = "9"
    elif mutation == "unit_total":
        payload["가"][first_unit]["E"] = "11"
        payload["가"][first_unit]["D"] = str(_count_sum(payload["가"][first_unit]))
    elif mutation == "unknown_unit":
        payload["나"][7]["A"] = "없는군"
    elif mutation == "missing_unit":
        del payload["나"][7:10]
    elif mutation == "duplicate_unit":
        payload["가"][10]["A"] = "가시동구"
    elif mutation == "voters_over_electors":
        payload["나"] = _sheet_rows_for("나도", [("나군", _bands(20, 200, 100), _bands(21, 170, 60))])
    elif mutation == "missing_sheet":
        del payload["나"]
    elif mutation == "header":
        payload["가"][3]["O"] = "80-89세"
    elif mutation == "text_cell":
        payload["가"][first_unit]["E"] = "모름"
    elif mutation == "blank_cell":
        del payload["가"][first_unit]["E"]
    else:
        payload["가"][2]["A"] = "표본 아님"
    with ZipFile(path, "w") as archive:
        archive.writestr(AGE_MEMBER, _workbook(payload))
    with pytest.raises(ValueError):
        read_age_table(path, crosswalk)


def _count_sum(row):
    return sum(int(str(row[column]).replace(",", "")) for column in BAND_COLUMNS)


def test_population_band_boundaries_and_open_age():
    ages = [17, 18, 19, 20, 24, 25, 39, 40, 49, 50, 59, 60, 69, 70, 79, 80, 100]
    population = pd.DataFrame(
        {"source_region_code": ["P1"] * len(ages), "age": ages, "population": range(1, len(ages) + 1)}
    )
    crosswalk = pd.DataFrame(
        {"dataset": ["population"], "source_region_code": ["P1"], "region_code": ["R1"]}
    )
    frame = pd.concat(
        [population, pd.DataFrame({"source_region_code": ["P1"], "age": [30], "population": [5]})]
    )
    table = population_bands(frame, crosswalk)
    row = table.loc["R1"]
    assert row["18"] == 2 and row["19"] == 3
    assert row["20-24"] == 4 + 5
    assert row["70-79"] == 14 + 15
    assert row["80+"] == 16 + 17
    assert "17" not in table.columns
    assert row.sum() == sum(range(2, 18)) + 5


def test_population_with_unmapped_region_or_missing_band_is_rejected():
    crosswalk = pd.DataFrame(
        {"dataset": ["population"], "source_region_code": ["P1"], "region_code": ["R1"]}
    )
    unmapped = pd.DataFrame({"source_region_code": ["P9"], "age": [20], "population": [1]})
    with pytest.raises(ValueError, match="대응되지 않은"):
        population_bands(unmapped, crosswalk)
    partial = pd.DataFrame({"source_region_code": ["P1"], "age": [20], "population": [1]})
    with pytest.raises(ValueError, match="비어 있는"):
        population_bands(partial, crosswalk)


def test_rates_and_expected_turnout_match_hand_calculation():
    age = pd.DataFrame(
        {
            **{f"e_{band}": [10, 10] for band in BANDS},
            **{f"v_{band}": [5, 5] for band in BANDS},
        },
        index=["R1", "R2"],
    )
    age.loc["R1", "e_80+"] = 100
    age.loc["R1", "v_80+"] = 60
    age.loc["R2", "e_80+"] = 300
    age.loc["R2", "v_80+"] = 240
    rates = national_rates(age)
    assert rates["80+"] == pytest.approx(300 / 400)
    bands = pd.DataFrame({band: [1.0, 3.0] for band in BANDS}, index=["R1", "R2"])
    weighted = population_weighted_rates(age, bands)
    assert weighted["80+"] == pytest.approx((1 * 0.6 + 3 * 0.8) / 4)
    shares = pd.DataFrame({band: [0.0] for band in BANDS}, index=["R1"])
    shares.loc["R1", "70-79"] = 0.5
    shares.loc["R1", "80+"] = 0.5
    expected = composition_expected(shares, pd.Series({**{b: 0.0 for b in BANDS}, "70-79": 0.9, "80+": 0.6}))
    assert expected["R1"] == pytest.approx(75)


def synthetic_frame(world="mixed"):
    """고정 인공 자료. 세계별로 알려진 성질을 검사한다."""
    rng = np.random.default_rng(1410)
    n = 144
    i = np.arange(n)
    aging = rng.uniform(15, 45, n)
    oldest = rng.uniform(12, 35, n)
    expected = 75 + 0.08 * aging - 0.1 * oldest
    frame = pd.DataFrame(
        {
            "region_code": [f"S{j:03d}" for j in i],
            "region_name": [f"인공{j}" for j in i],
            "aging_rate": aging,
            "oldest_share": oldest,
            "fiscal_independence": rng.uniform(10, 50, n),
            "net_migration_rate": rng.normal(0, 1, n),
            "log_population": rng.uniform(10, 13, n),
            "electors": rng.integers(10000, 500000, n).astype(float),
            "voters": 0.0,
            "region_type": np.array(["시", "군", "자치구"])[i % 3],
            "province": np.array(["광주광역시", "전라남도", "가상도", "나상도"])[i % 4],
            "composition_expected": expected,
            "direct_standardized": 80.0,
            "gap_80plus_minus_70s": -20.0,
            "gap_se_srs": 1.0,
            "sample_share_expected": expected,
        }
    )
    noise = rng.normal(0, 0.01 if world == "pure_composition" else 1.5, n)
    frame["turnout"] = expected + noise
    frame["within_age_difference"] = frame["turnout"] - frame["composition_expected"]
    frame["voters"] = frame["electors"] * frame["turnout"] / 100
    return frame


def _terms(coefficients, model, component):
    selected = coefficients.loc[
        (coefficients.model == model) & (coefficients.component == component)
    ]
    return selected.set_index("term")["estimate"]


def test_actual_coefficient_is_sum_of_two_parts_in_every_model():
    coefficients = fit_components(synthetic_frame())
    assert set(coefficients.model) == {"M1_common", "M2_common", "M3_common", "M4", "M4_WLS"}
    for model in coefficients.model.unique():
        actual = _terms(coefficients, model, "actual")
        total = _terms(coefficients, model, "composition") + _terms(coefficients, model, "within_age")
        np.testing.assert_allclose(actual, total.reindex(actual.index), atol=1e-8)


def test_pure_composition_world_leaves_nothing_for_within_age_part():
    coefficients = fit_components(synthetic_frame("pure_composition"))
    within = _terms(coefficients, "M4", "within_age")
    composition = _terms(coefficients, "M4", "composition")
    assert abs(within["oldest_share"]) < 0.002 and abs(within["aging_rate"]) < 0.002
    assert composition["oldest_share"] == pytest.approx(-0.1, abs=1e-8)
    assert composition["aging_rate"] == pytest.approx(0.08, abs=1e-8)


def test_constant_expected_turnout_is_not_reported_as_success():
    frame = synthetic_frame()
    frame["composition_expected"] = 79.0
    frame["within_age_difference"] = frame["turnout"] - 79.0
    with pytest.raises(ValueError, match="상수"):
        fit_components(frame)


def test_special_regions_are_excluded_like_m4():
    frame = synthetic_frame()
    frame.loc[0, "region_type"] = "특수지역"
    coefficients = fit_components(frame)
    assert set(coefficients.n) == {143}


def test_gap_summary_counts_regions_under_design_effects():
    frame = pd.DataFrame(
        {"gap_80plus_minus_70s": [-20.0, -10.0, 1.0], "gap_se_srs": [1.0, 3.0, 1.0]}
    )
    summary = gap_summary(frame)
    assert summary["regions_80plus_below_70s"] == 2
    counted = summary["regions_upper_bound_below_zero_by_design_effect"]
    assert counted["1"] == 2
    assert counted["4"] == 1
    assert summary["median"] == -10.0


def test_province_table_uses_counts_and_adjusts_for_expected_turnout():
    frame = pd.DataFrame(
        {
            "province": ["가도", "가도", "나도"],
            "electors": [100.0, 300.0, 400.0],
            "voters": [80.0, 240.0, 280.0],
            "composition_expected": [78.0, 78.0, 82.0],
            "direct_standardized": [80.0, 80.0, 70.0],
        }
    )
    table = province_table(frame).set_index("province")
    assert table.loc["가도", "actual_turnout"] == pytest.approx(80)
    assert table.loc["나도", "actual_turnout"] == pytest.approx(70)
    assert table.loc["가도", "age_adjusted_turnout"] == pytest.approx(80 - 78 + 80)
    assert table.loc["나도", "age_adjusted_turnout"] == pytest.approx(70 - 82 + 80)


def test_build_region_frame_identity_and_mismatch():
    bands = pd.DataFrame({band: [1.0, 1.0] for band in BANDS}, index=["R1", "R2"])
    age = pd.DataFrame(
        {**{f"e_{b}": [10, 10] for b in BANDS}, **{f"v_{b}": [8, 6] for b in BANDS}},
        index=["R1", "R2"],
    )
    data = pd.DataFrame(
        {
            "region_code": ["R1", "R2"],
            "turnout": [81.0, 59.0],
            "electors": [100.0, 100.0],
            "voters": [81.0, 59.0],
        }
    )
    frame = build_region_frame(data, age, bands).set_index("region_code")
    assert frame.loc["R1", "composition_expected"] == pytest.approx(70)
    assert frame.loc["R1", "within_age_difference"] == pytest.approx(11)
    assert frame.loc["R1", "rate_80plus"] == pytest.approx(80)
    assert frame.loc["R1", "gap_80plus_minus_70s"] == pytest.approx(0)
    assert frame.loc["R1", "direct_standardized"] == pytest.approx(80)
    with pytest.raises(ValueError, match="지역이 다릅니다"):
        build_region_frame(data.iloc[:1], age, bands)
    empty = age.copy()
    empty.loc["R1", "e_80+"] = 0
    with pytest.raises(ValueError, match="선거인이 0"):
        build_region_frame(data, empty, bands)


def test_sign_checks_report_competing_explanations_and_inapplicable_design():
    table = sign_checks(synthetic_frame()).set_index("check")
    assert {
        "M3_common",
        "without_X1",
        "include_special_regions",
        "exclude_m3_cook",
        "add_region_type",
        "add_honam_dummy",
        "exclude_honam",
        "add_province",
        "M4",
    } == set(table.index)
    assert pd.isna(table.loc["without_X1", "x1_estimate"])
    assert table.loc["exclude_honam", "n"] == 72
    assert table.loc["exclude_m3_cook", "n"] < 144
    alone = synthetic_frame()
    alone["province"] = "가상도"
    table = sign_checks(alone).set_index("check")
    assert table.loc["add_honam_dummy", "status"] == "NOT_APPLICABLE"
    assert table.loc["exclude_honam", "status"] == "PASS"


@pytest.fixture
def certified_run(tmp_path, monkeypatch):
    """파일 실행 경계용 인공 입력. 공식 수치 검증 증거로 쓰지 않는다."""
    rng = np.random.default_rng(77)
    monkeypatch.setattr(decomposition, "AGE_SHEETS", ("가",))
    n = 144
    base = synthetic_frame().drop(
        columns=[
            "composition_expected",
            "within_age_difference",
            "direct_standardized",
            "gap_80plus_minus_70s",
            "gap_se_srs",
            "sample_share_expected",
        ]
    )
    data = tmp_path / "analysis.csv"
    base.to_csv(data, index=False)
    units, map_rows, population = [], [], []
    for j in range(n):
        code = f"S{j:03d}"
        electors = [int(rng.integers(50, 300)) for _ in BANDS]
        voters = [int(e * rng.uniform(0.5, 0.95)) for e in electors]
        units.append((f"구{j}", electors, voters))
        map_rows.append(("election", f"가도|구{j}", code))
        map_rows.append(("population", f"P{j}", code))
        for age in [18, 19, 20, 25, 30, 35, 40, 50, 60, 70, 80]:
            population.append((f"P{j}", age, int(rng.integers(100, 900))))
    official = tmp_path / "official.zip"
    with ZipFile(official, "w") as archive:
        archive.writestr(AGE_MEMBER, _workbook({"가": _sheet_rows_for("가도", units)}))
    crosswalk = tmp_path / "crosswalk.csv"
    pd.DataFrame(map_rows, columns=["dataset", "source_region_code", "region_code"]).to_csv(
        crosswalk, index=False
    )
    people = tmp_path / "population.csv"
    pd.DataFrame(population, columns=["source_region_code", "age", "population"]).to_csv(
        people, index=False
    )
    code_dir = Path(pipeline.__file__).parent
    certified = [
        data,
        people,
        crosswalk,
        official,
        *(code_dir / name for name in pipeline.CERTIFICATE_CODE_FILES),
    ]
    quality = tmp_path / "quality.json"
    quality.write_text(
        json.dumps(
            {
                "input_contract_verified": True,
                "official_election_totals_verified": True,
                "dataset_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
                "verified_files": {
                    str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in certified
                },
            }
        )
    )
    return data, quality, people, crosswalk, official, tmp_path / "out"


def test_file_entry_writes_outputs_and_matching_manifest(certified_run):
    manifest = run_decomposition(*certified_run)
    output = certified_run[-1]
    assert manifest["exploratory_not_preregistered"] is True
    assert manifest["hypothesis_verdicts_changed"] is False
    for name, digest in manifest["artifacts"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert (output / "figures/decomposition_m4.png").stat().st_size > 0
    regions = pd.read_csv(output / "tables/decomposition_regions.csv")
    assert len(regions) == 144
    np.testing.assert_allclose(
        regions.turnout, regions.composition_expected + regions.within_age_difference
    )
    sensitivity = pd.read_csv(output / "tables/decomposition_sensitivity.csv")
    assert set(sensitivity.variant) == {
        "main_pooled_rates_population_shares",
        "population_weighted_rates",
        "sample_elector_shares",
    }


@pytest.mark.parametrize("mutation", ["unverified", "changed_data", "unbound_input"])
def test_file_entry_rejects_uncertified_inputs_without_outputs(certified_run, mutation):
    data, quality, people, crosswalk, official, output = certified_run
    record = json.loads(quality.read_text())
    if mutation == "unverified":
        record["official_election_totals_verified"] = False
    elif mutation == "unbound_input":
        del record["verified_files"][str(official.resolve())]
    quality.write_text(json.dumps(record))
    if mutation == "changed_data":
        with data.open("a") as handle:
            handle.write("\n")
    with pytest.raises(ValueError):
        run_decomposition(data, quality, people, crosswalk, official, output)
    assert not output.exists()


def test_sensitivity_table_reports_both_parts_for_each_variant():
    frame = synthetic_frame()
    codes = frame["region_code"]
    rng = np.random.default_rng(5)
    bands = pd.DataFrame({band: rng.uniform(1, 10, len(codes)) for band in BANDS}, index=codes)
    age = pd.DataFrame(
        {
            **{f"e_{b}": 10 for b in BANDS},
            **{f"v_{b}": 5 + position % 5 for position, b in enumerate(BANDS)},
        },
        index=codes,
    )
    frame["composition_expected"] = 70 + np.arange(len(codes)) * 0.01
    frame["sample_share_expected"] = 71 + np.arange(len(codes)) * 0.02
    table = sensitivity_table(frame, age, bands)
    assert len(table) == 12
    main = table.loc[(table.variant == "main_pooled_rates_population_shares")]
    assert set(main.term) == {"aging_rate", "oldest_share"}
