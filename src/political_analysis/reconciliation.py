"""공식 실제투표율과 교부수 기준 표를 범위를 구별하여 대조한다."""

from __future__ import annotations

import csv
import hashlib
import io
import posixpath
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd

SUMMARY_MEMBER = "01_투표율분석결과(표본)/01~10-투표율분석결과(표본).xlsx"
SUMMARY_SHEET = "01-실제투표율과 표본조사투표율"
DETAIL_MEMBER = "03_투표율분석결과(사전투표)/01-전체.xlsx"
DETAIL_SHEET = "01-전체투표율과사전투표율(종합)-나-구시군별"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def displayed_turnout(electors: int, voters: int) -> Decimal:
    """공식 표의 소수 첫째 자리, 양수의 사사오입을 적용한다."""
    return (Decimal(int(voters)) * 100 / Decimal(int(electors))).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def reported_turnout(value: str) -> Decimal:
    number = Decimal(value.replace(",", ""))
    rounded = number.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if abs(number - rounded) > Decimal("0.000000000001"):
        raise ValueError("공식 표시 투표율의 소수 첫째 자리 계약과 다릅니다.")
    return rounded


def _sheet_rows(archive: ZipFile, member: str, sheet_name: str) -> list[dict[str, str]]:
    """원본 XLSX의 저장된 셀 값을 읽는다. 수식 재계산·원본 수정은 하지 않는다."""
    with ZipFile(io.BytesIO(archive.read(member))) as workbook:
        strings = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            tree = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            strings = ["".join(e.itertext()) for e in tree.findall("s:si", NS)]
        tree = ET.fromstring(workbook.read("xl/workbook.xml"))
        sheets = [e for e in tree.findall("s:sheets/s:sheet", NS) if e.get("name") == sheet_name]
        if len(sheets) != 1:
            raise ValueError("공식 비교 원본의 시트가 없거나 중복됩니다.")
        relation_id = sheets[0].get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        relations = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        target = next(e.get("Target") for e in relations if e.get("Id") == relation_id)
        target = (
            target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        )
        tree = ET.fromstring(workbook.read(target))
        result = []
        for row in tree.findall("s:sheetData/s:row", NS):
            values = {"_row": row.get("r", "")}
            for cell in row.findall("s:c", NS):
                column = "".join(c for c in cell.get("r", "") if c.isalpha())
                value = cell.findtext("s:v", default="", namespaces=NS)
                if cell.get("t") == "s":
                    value = strings[int(value)]
                elif cell.get("t") == "inlineStr":
                    value = "".join(e.text or "" for e in cell.findall("s:is//s:t", NS))
                values[column] = value
            result.append(values)
        return result


def _count(value: str) -> int:
    number = Decimal(value.replace(",", ""))
    if not number.is_finite() or number < 0 or number != int(number):
        raise ValueError("공식 선거 계수는 0 이상의 정수여야 합니다.")
    return int(number)


def reconcile_election(
    staged: pd.DataFrame,
    crosswalk: pd.DataFrame,
    raw_source: Path,
    official_zip: Path,
    output: Path,
) -> dict:
    """직접 대조와 같은 원본을 재사용한 범위 조정을 명확히 구분한다."""
    lookup = crosswalk.loc[crosswalk["dataset"] == "election"]
    sources = staged.merge(lookup, on="source_region_code", validate="one_to_one")
    source_map = sources.set_index("source_region_code").to_dict("index")
    provinces = set(sources["province"])
    components = defaultdict(lambda: defaultdict(int))
    with raw_source.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["후보자"] != "투표수":
                continue
            key = row["시도명"] + "|" + row["구시군명"]
            if key not in source_map:
                raise ValueError("대조용 개표 원본에 미확인 지역이 있습니다.")
            town, polling = row["읍면동명"], row["투표구명"]
            if town == "관외사전투표" or polling == "관내사전투표":
                category = "early"
            elif town == "거소·선상투표":
                category = "residence_ship"
            elif town == "재외투표":
                category = "overseas"
            else:
                # 공식 지역별 표의 선거일 결과는 잘못 투입·구분된 투표지도 포함한다.
                category = "day"
            components[key][category] += _count(row["득표수"])
    if set(components) != set(source_map):
        raise ValueError("대조용 개표 원본의 지역이 누락되었습니다.")
    with ZipFile(official_zip) as archive:
        summary = _sheet_rows(archive, SUMMARY_MEMBER, SUMMARY_SHEET)
        detail = _sheet_rows(archive, DETAIL_MEMBER, DETAIL_SHEET)
    notes = [row for row in detail if "※" in row.get("A", "")]
    note_text = " ".join(row["A"] for row in notes)
    if not all(word in note_text for word in ["교부수", "개표기준", "다름"]):
        raise ValueError("교부수/개표 기준 차이의 공식 주석이 확인되지 않습니다.")
    records = []
    seen = set()
    for row in summary:
        key = row.get("A", "")
        if key not in provinces | {"전국"}:
            continue
        if key in seen:
            raise ValueError("공식 실제투표율 표에 집계 중복이 있습니다.")
        seen.add(key)
        subset = sources if key == "전국" else sources.loc[sources["province"] == key]
        electors, voters = int(subset["electors"].sum()), int(subset["voters"].sum())
        official_electors, official_voters = _count(row["C"]), _count(row["F"])
        rate_ok = displayed_turnout(electors, voters) == reported_turnout(row["G"])
        ok = electors == official_electors and voters == official_voters and rate_ok
        records.append(
            {
                "level": "national" if key == "전국" else "province",
                "key": key,
                "computed_electors": electors,
                "official_electors": official_electors,
                "counted_voters": voters,
                "official_voters_original": official_voters,
                "basis_difference": 0,
                "official_voters_adjusted": official_voters,
                "difference_before_adjustment": official_voters - voters,
                "difference_after_adjustment": official_voters - voters,
                "official_reported_turnout": row["G"],
                "status": "PASS" if ok else "FAIL",
                "verification_kind": "direct_counted_result_comparison",
                "source_member": SUMMARY_MEMBER,
                "source_sheet": SUMMARY_SHEET,
                "source_row": row["_row"],
            }
        )
    if seen != provinces | {"전국"}:
        raise ValueError("공식 실제투표율 표의 전국·시도 범위가 다릅니다.")
    seen = set()
    regional_records = []
    for row in detail:
        key = row.get("A", "") + "|" + row.get("B", "")
        if key not in source_map:
            continue
        if key in seen:
            raise ValueError("공식 지역별 분석표의 구역이 중복됩니다.")
        seen.add(key)
        computed = source_map[key]
        parts = components[key]
        electors, voters = int(computed["electors"]), int(computed["voters"])
        reported = _count(row["G"])
        issued = _count(row["I"])
        other = {
            "day": _count(row["M"]),
            "residence_ship": _count(row["Q"]),
            "overseas": _count(row["U"]),
        }
        basis_difference = issued - parts["early"]
        adjusted = reported - basis_difference
        ok = (
            _count(row["D"]) == electors
            and sum(parts.values()) == voters
            and all(parts[name] == count for name, count in other.items())
            and reported == issued + sum(other.values())
            and adjusted == voters
            and displayed_turnout(electors, reported) == reported_turnout(row["H"])
        )
        record = {
            "level": "source_region",
            "key": key,
            "region_code": computed["region_code"],
            "province": computed["province"],
            "computed_electors": electors,
            "official_electors": _count(row["D"]),
            "counted_voters": voters,
            "official_voters_original": reported,
            "early_ballots_issued": issued,
            "early_ballots_counted": parts["early"],
            "basis_difference": basis_difference,
            "official_voters_adjusted": adjusted,
            "difference_before_adjustment": reported - voters,
            "difference_after_adjustment": adjusted - voters,
            "official_reported_turnout": str(reported_turnout(row["H"])),
            "official_stored_turnout": row["H"],
            "status": "PASS" if ok else "FAIL",
            "verification_kind": "scope_adjustment_reuses_counted_early_ballots",
            "source_member": DETAIL_MEMBER,
            "source_sheet": DETAIL_SHEET,
            "source_row": row["_row"],
        }
        regional_records.append(record)
    if seen != set(source_map):
        raise ValueError("공식 지역별 분석표에 대상 원본 구역이 누락되었습니다.")
    records.extend(regional_records)
    regions = defaultdict(list)
    for record in regional_records:
        regions[record["region_code"]].append(record)
    for region, rows in sorted(regions.items()):
        fields = [
            "computed_electors",
            "official_electors",
            "counted_voters",
            "official_voters_original",
            "early_ballots_issued",
            "early_ballots_counted",
            "basis_difference",
            "official_voters_adjusted",
            "difference_before_adjustment",
            "difference_after_adjustment",
        ]
        records.append(
            {
                "level": "analysis_region",
                "key": region,
                "region_code": region,
                "province": rows[0]["province"],
                **{field: sum(row[field] for row in rows) for field in fields},
                "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
                "verification_kind": "aggregated_scope_adjustment_not_independent_reverification",
                "source_member": DETAIL_MEMBER,
                "source_sheet": DETAIL_SHEET,
                "source_row": ";".join(row["source_row"] for row in rows),
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_csv(output, index=False, encoding="utf-8")
    if any(row["status"] != "PASS" for row in records):
        raise ValueError("공식 선거 대조에 미해결 차이가 있습니다. 대조 CSV를 확인하세요.")
    return {
        "official_election_totals_verified": True,
        "direct_summary_rows": len(provinces) + 1,
        "source_region_rows": len(regional_records),
        "analysis_region_rows": len(regions),
        "original_regional_voter_difference": sum(
            row["difference_before_adjustment"] for row in regional_records
        ),
        "adjusted_residual": sum(row["difference_after_adjustment"] for row in regional_records),
        "regional_adjustment_is_independent_reverification": False,
        "official_zip_sha256": hashlib.sha256(official_zip.read_bytes()).hexdigest(),
        "reconciliation_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "basis_note_rows": [row["_row"] for row in notes],
        "note": "전국·시도는 직접 대조. 지역별은 공식 주석에 따른 교부수/개표수 조정이며 같은 원본을 재사용함.",
    }
