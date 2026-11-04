"""작은 OOXML 인공 표로 직접 대조·범위 조정·비독립성을 검증한다."""

import csv
import io
from decimal import Decimal
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd
import pytest

from political_analysis.reconciliation import (
    DETAIL_MEMBER,
    DETAIL_SHEET,
    SUMMARY_MEMBER,
    SUMMARY_SHEET,
    displayed_turnout,
    reconcile_election,
    reported_turnout,
)


def _workbook(sheet_name, rows):
    """외부 라이브러리 없는 parser용 최소 ZIP/XML fixture이며 전달용 workbook이 아니다."""
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = ET.Element("worksheet", xmlns=namespace)
    body = ET.SubElement(sheet, "sheetData")
    for index, cells in enumerate(rows, start=1):
        row = ET.SubElement(body, "row", r=str(index))
        for column, value in cells.items():
            cell = ET.SubElement(row, "c", r=f"{column}{index}", t="inlineStr")
            ET.SubElement(ET.SubElement(cell, "is"), "t").text = str(value)
    workbook = ET.Element("workbook", xmlns=namespace)
    sheets = ET.SubElement(workbook, "sheets")
    ET.SubElement(
        sheets,
        "sheet",
        name=sheet_name,
        attrib={"{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": "rId1"},
    )
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", ET.tostring(workbook))
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet))
    return output.getvalue()


@pytest.fixture
def official_case(tmp_path):
    staged = pd.DataFrame(
        {
            "source_region_code": ["가도|가시", "가도|나군"],
            "electors": [100, 200],
            "voters": [70, 150],
        }
    )
    crosswalk = pd.DataFrame(
        {
            "dataset": ["election"] * 2,
            "source_region_code": ["가도|가시", "가도|나군"],
            "region_code": ["R1", "R2"],
            "province": ["가도"] * 2,
        }
    )
    raw = tmp_path / "raw.csv"
    with raw.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["시도명", "구시군명", "읍면동명", "투표구명", "후보자", "득표수"])
        for district, early, day in [("가시", 20, 50), ("나군", 30, 120)]:
            writer.writerow(["가도", district, "가동", "관내사전투표", "투표수", early])
            writer.writerow(["가도", district, "가동", "제1투표구", "투표수", day])
    summary = [
        {"A": "전국", "C": "300", "F": "220", "G": "73.3"},
        {"A": "가도", "C": "300", "F": "220", "G": "73.3"},
    ]
    detail = [
        {
            "A": "가도",
            "B": "가시",
            "D": "100",
            "G": "72",
            "H": "72.0",
            "I": "22",
            "M": "50",
            "Q": "0",
            "U": "0",
        },
        {
            "A": "가도",
            "B": "나군",
            "D": "200",
            "G": "150",
            "H": "75.0",
            "I": "30",
            "M": "120",
            "Q": "0",
            "U": "0",
        },
        {"A": "※ 사전투표는 교부수, 나머지는 개표기준이므로 전체 결과가 다름"},
    ]
    return (
        staged,
        crosswalk,
        raw,
        tmp_path / "official.zip",
        tmp_path / "comparison.csv",
        summary,
        detail,
    )


def _run(case):
    staged, crosswalk, raw, path, output, summary, detail = case
    with ZipFile(path, "w") as archive:
        archive.writestr(SUMMARY_MEMBER, _workbook(SUMMARY_SHEET, summary))
        archive.writestr(DETAIL_MEMBER, _workbook(DETAIL_SHEET, detail))
    return reconcile_election(staged, crosswalk, raw, path, output)


def test_direct_summary_and_basis_adjustment_are_distinct(official_case):
    result = _run(official_case)
    assert result["official_election_totals_verified"]
    assert result["direct_summary_rows"] == 2
    assert result["original_regional_voter_difference"] == 2
    assert result["adjusted_residual"] == 0
    assert not result["regional_adjustment_is_independent_reverification"]
    rows = pd.read_csv(official_case[4])
    first = rows.loc[(rows.level == "source_region") & (rows.key == "가도|가시")].iloc[0]
    assert first.official_voters_original == 72 and first.counted_voters == 70
    assert first.basis_difference == 2 and first.difference_after_adjustment == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "summary_count",
        "missing_summary",
        "missing_region",
        "duplicate_region",
        "no_basis_note",
        "wrong_non_early_component",
    ],
)
def test_unresolved_official_difference_rejected(official_case, mutation):
    summary, detail = official_case[-2:]
    if mutation == "summary_count":
        summary[0]["F"] = "221"
    elif mutation == "missing_summary":
        del summary[1]
    elif mutation == "missing_region":
        del detail[0]
    elif mutation == "duplicate_region":
        detail.insert(0, detail[0].copy())
    elif mutation == "no_basis_note":
        detail[-1]["A"] = "주석 없음"
    else:
        detail[0]["M"] = "51"
        detail[0]["G"] = "73"
        detail[0]["H"] = "73.0"
    with pytest.raises(ValueError):
        _run(official_case)


def test_displayed_precision_is_not_a_broad_tolerance():
    assert displayed_turnout(2000, 1589) == Decimal("79.5")
    assert reported_turnout("79.099999999999994") == Decimal("79.1")
    with pytest.raises(ValueError):
        reported_turnout("79.14")
