"""분해 결과의 독립 재계산 (ADR-014).

생산 모듈과 statsmodels를 쓰지 않고 표준 라이브러리와 numpy로 원본부터 다시 계산한다.
같은 원본을 다른 코드로 대조하는 것이며 독립된 자료에 의한 재현은 아니다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import posixpath
import re
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np

MEMBER = "01_투표율분석결과(표본)/11-성별·연령대별 투표율(구시군별).xlsx"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
COLUMNS = "EFGHIJKLMNO"
BAND_LOWER = [18, 19, 20, 25, 30, 35, 40, 50, 60, 70, 80]
RTOL, ATOL = 1e-8, 1e-9
Z = NormalDist().inv_cdf(0.975)
CONTROLS = ["fiscal_independence", "net_migration_rate", "log_population"]
AGE_TERMS = ["aging_rate", "oldest_share"]
MODELS = {
    "M1_common": (["aging_rate"], False, False),
    "M2_common": (AGE_TERMS, False, False),
    "M3_common": (AGE_TERMS + CONTROLS, False, False),
    "M4": (AGE_TERMS + CONTROLS, True, False),
    "M4_WLS": (AGE_TERMS + CONTROLS, True, True),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path, encoding="utf-8-sig"):
    with open(path, encoding=encoding, newline="") as handle:
        return list(csv.DictReader(handle))


def close(a, b):
    return math.isclose(float(a), float(b), rel_tol=RTOL, abs_tol=ATOL)


def workbook_rows(zip_path):
    """저장된 셀 값을 시트별 행 사전으로 읽는다."""
    with ZipFile(zip_path) as outer:
        book = ZipFile(io.BytesIO(outer.read(MEMBER)))
    strings = [
        "".join(item.itertext())
        for item in ET.fromstring(book.read("xl/sharedStrings.xml")).findall("s:si", NS)
    ]
    targets = {e.get("Id"): e.get("Target") for e in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
    sheets = {}
    for sheet in ET.fromstring(book.read("xl/workbook.xml")).findall("s:sheets/s:sheet", NS):
        target = targets[sheet.get(REL)]
        target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        rows = []
        for row in ET.fromstring(book.read(target)).findall("s:sheetData/s:row", NS):
            cells = {}
            for cell in row.findall("s:c", NS):
                column = "".join(ch for ch in cell.get("r") if ch.isalpha())
                value = cell.findtext("s:v", default="", namespaces=NS)
                cells[column] = strings[int(value)] if cell.get("t") == "s" else value
            rows.append(cells)
        sheets[sheet.get("name")] = rows
    return sheets


def number(text):
    return int(str(text).replace(",", ""))


def age_counts(zip_path, election_lookup):
    electors = defaultdict(lambda: [0] * 11)
    voters = defaultdict(lambda: [0] * 11)
    seen, rows_checked = set(), 0
    for rows in workbook_rows(zip_path).values():
        province = re.search(r"\[표본\]\[(.+)\]", rows[2]["A"]).group(1)
        total = None
        summed = [[0] * 11, [0] * 11]
        for i, row in enumerate(rows):
            if row.get("B") != "합계" or row.get("C") != "선거인수":
                continue
            assert rows[i + 1]["C"] == "투표자수"
            e = [number(row[c]) for c in COLUMNS]
            v = [number(rows[i + 1][c]) for c in COLUMNS]
            assert sum(e) == number(row["D"]) and sum(v) == number(rows[i + 1]["D"])
            rows_checked += 1
            unit = row["A"].strip()
            if unit == "전체":
                total = [e, v]
                continue
            key = f"{province}|{unit}"
            assert key not in seen
            seen.add(key)
            summed = [[a + b for a, b in zip(summed[0], e)], [a + b for a, b in zip(summed[1], v)]]
            code = election_lookup[key]
            electors[code] = [a + b for a, b in zip(electors[code], e)]
            voters[code] = [a + b for a, b in zip(voters[code], v)]
        assert total == summed
    assert seen == set(election_lookup)
    return electors, voters, rows_checked


def population_shares(path, lookup):
    counts = defaultdict(lambda: [0] * 11)
    for row in read_csv(path):
        age = int(row["age"])
        if age < 18:
            continue
        position = max(i for i, lower in enumerate(BAND_LOWER) if age >= lower)
        counts[lookup[row["source_region_code"]]][position] += int(row["population"])
    return counts


def design_matrix(rows, terms, fixed_effects):
    columns = {"Intercept": [1.0] * len(rows)}
    for term in terms:
        columns[term] = [float(row[term]) for row in rows]
    if fixed_effects:
        for factor in ["region_type", "province"]:
            for level in sorted({row[factor] for row in rows})[1:]:
                columns[f"C({factor})[T.{level}]"] = [float(row[factor] == level) for row in rows]
    return list(columns), np.column_stack(list(columns.values()))


def hc3(x, y, weights):
    root = np.sqrt(weights)
    xw, yw = x * root[:, None], y * root
    bread = np.linalg.inv(xw.T @ xw)
    beta = bread @ xw.T @ yw
    residual = yw - xw @ beta
    leverage = np.einsum("ij,jk,ik->i", xw, bread, xw)
    meat = xw.T @ ((residual / (1 - leverage))[:, None] ** 2 * xw)
    se = np.sqrt(np.diag(bread @ meat @ bread))
    return beta, se


def audit(run_dir, data_path, population_path, crosswalk_path, zip_path):
    tables = run_dir / "tables"
    manifest = json.loads((run_dir / "decomposition_manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["artifacts"].items():
        assert sha(run_dir / name) == digest, name
    assert sha(data_path) == manifest["dataset_sha256"]

    crosswalk = read_csv(crosswalk_path)
    election = {r["source_region_code"]: r["region_code"] for r in crosswalk if r["dataset"] == "election"}
    population = {r["source_region_code"]: r["region_code"] for r in crosswalk if r["dataset"] == "population"}
    electors, voters, rows_checked = age_counts(zip_path, election)
    counts = population_shares(population_path, population)
    data = {row["region_code"]: row for row in read_csv(data_path)}
    assert set(data) == set(electors) == set(counts)

    rates = [
        sum(voters[c][i] for c in data) / sum(electors[c][i] for c in data) for i in range(11)
    ]
    national = [sum(electors[c][i] for c in data) for i in range(11)]
    national_total = sum(national)
    produced = {row["region_code"]: row for row in read_csv(tables / "decomposition_regions.csv")}
    assert set(produced) == set(data)
    derived, cells = {}, 0
    for code, row in data.items():
        total = sum(counts[code])
        expected = 100 * sum(share / total * rate for share, rate in zip(counts[code], rates))
        difference = float(row["turnout"]) - expected
        r80 = voters[code][10] / electors[code][10]
        r70 = voters[code][9] / electors[code][9]
        standardized = 100 * sum(
            national[i] / national_total * voters[code][i] / electors[code][i] for i in range(11)
        )
        derived[code] = {
            "composition_expected": expected,
            "within_age_difference": difference,
            "rate_80plus": 100 * r80,
            "rate_70s": 100 * r70,
            "gap_80plus_minus_70s": 100 * (r80 - r70),
            "gap_se_srs": 100 * math.sqrt(
                r80 * (1 - r80) / electors[code][10] + r70 * (1 - r70) / electors[code][9]
            ),
            "direct_standardized": standardized,
            "sample_electors": sum(electors[code]),
            "sample_voters": sum(voters[code]),
        }
        for name, value in derived[code].items():
            assert close(produced[code][name], value), (code, name)
            cells += 1

    sample = sorted(
        (
            {**row, **derived[code], "turnout": float(row["turnout"])}
            for code, row in data.items()
            if row["region_type"] != "특수지역"
        ),
        key=lambda row: row["region_code"],
    )
    produced_coef = defaultdict(dict)
    for row in read_csv(tables / "decomposition_coefficients.csv"):
        produced_coef[(row["model"], row["component"])][row["term"]] = row
    largest = {"estimate": 0.0, "std_error_hc3": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    coefficient_cells = 0
    additivity = 0.0
    outcomes = {
        "actual": "turnout",
        "composition": "composition_expected",
        "within_age": "within_age_difference",
    }
    for model, (terms, fixed_effects, weighted) in MODELS.items():
        names, x = design_matrix(sample, terms, fixed_effects)
        weights = np.array([float(r["electors"]) for r in sample]) if weighted else np.ones(len(sample))
        betas = {}
        for component, column in outcomes.items():
            y = np.array([float(r[column]) for r in sample])
            beta, se = hc3(x, y, weights)
            betas[component] = beta
            assert set(produced_coef[(model, component)]) == set(names)
            for position, term in enumerate(names):
                row = produced_coef[(model, component)][term]
                expected = {
                    "estimate": beta[position],
                    "std_error_hc3": se[position],
                    "ci_low": beta[position] - Z * se[position],
                    "ci_high": beta[position] + Z * se[position],
                }
                for field, value in expected.items():
                    assert close(row[field], value), (model, component, term, field)
                    largest[field] = max(largest[field], abs(float(row[field]) - value))
                    coefficient_cells += 1
        additivity = max(
            additivity,
            float(np.max(np.abs(betas["actual"] - betas["composition"] - betas["within_age"]))),
        )

    # 시도별 조정 투표율
    weights = {c: float(data[c]["electors"]) for c in data}
    national_expected = sum(derived[c]["composition_expected"] * weights[c] for c in data) / sum(weights.values())
    groups = defaultdict(list)
    for code in data:
        groups[data[code]["province"]].append(code)
    province_cells = 0
    for row in read_csv(tables / "decomposition_provinces.csv"):
        codes = groups[row["province"]]
        total = sum(weights[c] for c in codes)
        actual = 100 * sum(float(data[c]["voters"]) for c in codes) / total
        expected = sum(derived[c]["composition_expected"] * weights[c] for c in codes) / total
        for name, value in {
            "actual_turnout": actual,
            "composition_expected": expected,
            "age_adjusted_turnout": actual - expected + national_expected,
        }.items():
            assert close(row[name], value), (row["province"], name)
            province_cells += 1

    gaps = [derived[c]["gap_80plus_minus_70s"] for c in data]
    summary = manifest["gaps"]
    assert summary["regions_80plus_below_70s"] == sum(g < 0 for g in gaps)
    assert close(summary["min"], min(gaps)) and close(summary["max"], max(gaps))
    assert close(summary["median"], float(np.median(gaps)))
    for effect, count in summary["regions_upper_bound_below_zero_by_design_effect"].items():
        recomputed = sum(
            derived[c]["gap_80plus_minus_70s"] + Z * derived[c]["gap_se_srs"] * math.sqrt(int(effect)) < 0
            for c in data
        )
        assert count == recomputed, effect
    turnout = np.array([float(data[c]["turnout"]) for c in data])
    expected = np.array([derived[c]["composition_expected"] for c in data])
    variance = manifest["variance"]
    assert close(variance["sd_actual"], turnout.std(ddof=1))
    assert close(variance["sd_composition"], expected.std(ddof=1))
    assert close(variance["sd_within_age"], (turnout - expected).std(ddof=1))
    assert close(variance["corr_composition_actual"], np.corrcoef(expected, turnout)[0, 1])

    report = {
        "gate": "G-POST-02",
        "status": "decomposition_independently_recomputed",
        "method": "stdlib XML/CSV parser and numpy normal equations; no production module or statsmodels",
        "independence_scope": "same raw inputs, separate code; not an independent data source",
        "audit_code_sha256": sha(Path(__file__)),
        "manifest_sha256": sha(run_dir / "decomposition_manifest.json"),
        "dataset_sha256": manifest["dataset_sha256"],
        "tolerance": {"relative": RTOL, "absolute": ATOL},
        "age_table_rows_checked": rows_checked,
        "region_cells_checked": cells,
        "coefficient_cells_checked": coefficient_cells,
        "province_cells_checked": province_cells,
        "maximum_absolute_errors": largest,
        "maximum_additivity_error": additivity,
    }
    (run_dir / "decomposition_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("outputs/current"))
    parser.add_argument("--population", type=Path, default=Path("data/interim/population.csv"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/reference/region_crosswalk.csv"))
    parser.add_argument(
        "--official-election-zip",
        type=Path,
        default=Path("data/raw/제21대 대통령선거 투표율 분석.zip"),
    )
    args = parser.parse_args()
    report = audit(
        args.run_dir,
        args.run_dir / "analysis_dataset.csv",
        args.population,
        args.crosswalk,
        args.official_election_zip,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
