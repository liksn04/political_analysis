"""실제로 확인한 공식 원본을 코드북의 표준 입력으로 변환한다."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

ELECTION_CONTEXT = ["시도명", "구시군명", "읍면동명", "투표구명"]
SPECIAL_VOTING_ROWS = {"거소·선상투표", "관외사전투표", "재외투표", "잘못 투입·구분된 투표지"}


def stage_election(source: Path, crosswalk: Path, output: Path, report: Path) -> pd.DataFrame:
    """구역별 계수를 보존한다. 시 통합과 공식 합계 대조는 후속 단계다."""
    frame = pd.read_csv(source, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    required = set(ELECTION_CONTEXT + ["후보자", "득표수"])
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError("선거 원본의 필수 열 또는 데이터가 없습니다.")
    counts = frame.loc[frame["후보자"].isin(["선거인수", "투표수"])].copy()
    if counts.empty:
        raise ValueError("선거인수·투표수 행이 없습니다.")
    if counts[ELECTION_CONTEXT[:3]].eq("").any().any():
        raise ValueError("선거 원본의 지역·읍면동 식별자가 비어 있습니다.")
    if (counts["투표구명"].eq("") & ~counts["읍면동명"].isin(SPECIAL_VOTING_ROWS)).any():
        raise ValueError("투표구 없는 미확인 집계 행: 상하위 합계 혼입을 확인하세요.")
    if counts.duplicated(ELECTION_CONTEXT + ["후보자"]).any():
        raise ValueError("원본 투표구·집계항목 중복입니다.")
    numeric = pd.to_numeric(counts["득표수"], errors="coerce")
    if not np.isfinite(numeric).all() or (numeric < 0).any() or (numeric % 1 != 0).any():
        raise ValueError("선거인수·투표수는 0 이상의 정수여야 합니다.")
    counts["득표수"] = numeric.astype("int64")
    wide = counts.pivot(index=ELECTION_CONTEXT, columns="후보자", values="득표수")
    if not {"선거인수", "투표수"}.issubset(wide.columns) or wide.isna().any().any():
        raise ValueError("같은 투표구의 선거인수·투표수 쌍이 누락되었습니다.")
    wide = wide.reset_index()
    wide["source_region_code"] = wide["시도명"] + "|" + wide["구시군명"]
    result = wide.groupby("source_region_code", as_index=False)[["선거인수", "투표수"]].sum()
    result = result.rename(columns={"선거인수": "electors", "투표수": "voters"})
    lookup = pd.read_csv(crosswalk, dtype=str, keep_default_na=False)
    if not {"dataset", "source_region_code"}.issubset(lookup.columns):
        raise ValueError("지역 대응표 필수 열 누락입니다.")
    expected = lookup.loc[lookup["dataset"] == "election", "source_region_code"]
    if expected.duplicated().any() or set(result["source_region_code"]) != set(expected):
        raise ValueError("선거 원본 구역과 대응표의 범위가 다르거나 키가 중복됩니다.")
    if (result["electors"] <= 0).any() or (result["voters"] > result["electors"]).any():
        raise ValueError("원본 구역의 선거인수·투표수 범위가 잘못되었습니다.")
    details = {
        "status": "election_staging_internal_checks_passed",
        "official_election_totals_verified": False,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "crosswalk_sha256": hashlib.sha256(crosswalk.read_bytes()).hexdigest(),
        "raw_rows": len(frame),
        "voting_contexts": len(wide),
        "staged_source_regions": len(result),
        "electors": int(result["electors"].sum()),
        "voters": int(result["voters"].sum()),
        "note": "원본 집계항목·투표구 중복과 코드 범위 검사. 공식 합계 대조는 미완료.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8")
    details["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    report.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def stage_population(
    source: Path, crosswalk: Path, inventory: Path, output: Path, report: Path, checks: Path
) -> pd.DataFrame:
    """2025-05 전체 인구의 0~99세·100세 이상을 빠짐없이 보존한다."""
    prefix = "2025년05월_계_"
    age_columns = [f"{prefix}{age}세" for age in range(100)] + [f"{prefix}100세 이상"]
    total_column = prefix + "총인구수"
    interval_column = prefix + "연령구간인구수"
    required = ["행정구역", total_column, interval_column] + age_columns
    with source.open(encoding="cp949", newline="") as handle:
        header = next(csv.reader(handle), [])
    if len(header) != len(set(header)) or set(header) != set(required):
        raise ValueError("인구 원본의 기준월·전체 연령 열이 다르거나 중복되어 있습니다.")
    frame = pd.read_csv(source, encoding="cp949", dtype=str, keep_default_na=False)
    codes = frame["행정구역"].str.extract(r"\((\d{10})\)\s*$", expand=False)
    if frame.empty or codes.isna().any() or codes.duplicated().any():
        raise ValueError("인구 원본의 지역코드 누락·중복입니다.")
    frame = frame.assign(source_region_code=codes)
    lookup = pd.read_csv(crosswalk, dtype=str, keep_default_na=False)
    ledger = pd.read_csv(inventory, dtype=str, keep_default_na=False)
    if not {"dataset", "source_region_code", "region_code"}.issubset(lookup.columns):
        raise ValueError("인구 대응표의 필수 열 누락입니다.")
    if not {"dataset", "source_region_code", "region_code", "disposition"}.issubset(ledger.columns):
        raise ValueError("인구 원본 대장의 필수 열 누락입니다.")
    lookup = lookup.loc[lookup["dataset"] == "population"]
    ledger = ledger.loc[ledger["dataset"] == "population"]
    selected_ledger = ledger.loc[ledger["region_code"].ne("")]
    if (
        lookup.empty
        or lookup["source_region_code"].eq("").any()
        or lookup["region_code"].eq("").any()
        or lookup["source_region_code"].duplicated().any()
        or lookup["region_code"].duplicated().any()
        or ledger["source_region_code"].duplicated().any()
        or set(codes) != set(ledger["source_region_code"])
        or dict(zip(lookup["source_region_code"], lookup["region_code"]))
        != dict(zip(selected_ledger["source_region_code"], selected_ledger["region_code"]))
    ):
        raise ValueError("인구 원본·대응표·포함/제외 대장의 범위가 다르거나 중복됩니다.")
    selected = frame.loc[frame["source_region_code"].isin(lookup["source_region_code"])].copy()
    numeric_columns = [total_column, interval_column] + age_columns
    values = selected[numeric_columns].apply(lambda column: column.str.strip())
    if (
        not values.apply(lambda column: column.str.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)"))
        .all()
        .all()
    ):
        raise ValueError("인구 계수에 누락·음수·소수·문자열 또는 잘못된 쉼표가 있습니다.")
    values = values.replace(",", "", regex=True).astype("int64")
    age_sum = values[age_columns].sum(axis=1)
    if (age_sum != values[total_column]).any() or (age_sum != values[interval_column]).any():
        raise ValueError("지역별 전체 연령 합계가 원본 총인구·연령구간인구와 다릅니다.")
    selected[age_columns] = values[age_columns]
    result = selected[["source_region_code"] + age_columns].melt(
        id_vars="source_region_code", var_name="age", value_name="population"
    )
    result["age"] = result["age"].map(dict(zip(age_columns, range(101)))).astype("int64")
    result["population"] = result["population"].astype("int64")
    result = result.sort_values(["source_region_code", "age"]).reset_index(drop=True)
    audit = selected[["source_region_code"]].copy()
    audit["population_total"] = values[total_column]
    audit["sum_all_ages"] = age_sum
    audit["age_bins"] = len(age_columns)
    for age in [18, 65, 80]:
        audit[f"population_{age}plus"] = values[age_columns[age:]].sum(axis=1)
    audit = audit.merge(lookup[["source_region_code", "region_code"]], validate="one_to_one")
    audit = audit.sort_values("source_region_code")
    details = {
        "status": "population_staging_internal_checks_passed",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "crosswalk_sha256": hashlib.sha256(crosswalk.read_bytes()).hexdigest(),
        "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
        "raw_regions": len(frame),
        "selected_regions": len(selected),
        "excluded_regions": len(frame) - len(selected),
        "rows": len(result),
        "expected_ages": list(range(101)),
        "open_age_bin": "100 represents 100 years and above",
        "reference_month": "2025-05",
        "same_source_totals_matched": True,
        "population_totals": {
            column: int(audit[column].sum())
            for column in [
                "population_total",
                "population_18plus",
                "population_65plus",
                "population_80plus",
            ]
        },
        "note": "원본 내부 합계·연령 완전성 검사. 독립 공식 합계 및 전체 자료 결합은 별도.",
    }
    for path in [output, report, checks]:
        path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8")
    audit.to_csv(checks, index=False, encoding="utf-8")
    details["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    details["checks_sha256"] = hashlib.sha256(checks.read_bytes()).hexdigest()
    report.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def stage_fiscal(
    source: Path,
    crosswalk: Path,
    inventory: Path,
    definition: Path,
    output: Path,
    report: Path,
    checks: Path,
) -> pd.DataFrame:
    """당초·개편후 재정자립도 한 값을 보존하고 결측은 별도로 기록한다."""
    spec = json.loads(definition.read_text(encoding="utf-8"))["byatcSituPbaIndcInfoInqRsltDto"]
    explanation = html.unescape(spec["menuDtsEplCn"])
    if str(spec["fyr"]) != "2025" or not all(
        text in explanation
        for text in [
            "재정자립도[당초](개편후)",
            "산정기준:예산, 당초",
            "대상회계:일반회계",
            "기준연도:2025",
        ]
    ):
        raise ValueError("재정 지표의 연도·당초·개편후·회계 기준이 다릅니다.")
    data = json.loads(source.read_text(encoding="utf-8"))
    frame = pd.DataFrame(data["firFrsIxInqRsltDto"])
    if frame.empty or not {"fyr", "lafNm", "firRt"}.issubset(frame.columns):
        raise ValueError("재정 원본의 데이터·필수 열이 없습니다.")
    if frame["lafNm"].isna().any() or frame["lafNm"].eq("").any():
        raise ValueError("재정 원본 기관명이 비어 있습니다.")
    if frame["lafNm"].duplicated().any():
        raise ValueError("재정 원본 기관명이 중복됩니다. 비율 합산 금지.")
    if not frame["fyr"].isin(["", "2025", 2025]).all():
        raise ValueError("재정 원본 행의 기준연도가 다릅니다.")
    lookup = pd.read_csv(crosswalk, dtype=str, keep_default_na=False)
    ledger = pd.read_csv(inventory, dtype=str, keep_default_na=False)
    required = {"dataset", "source_region_code", "region_code"}
    if not required.issubset(lookup.columns) or not (required | {"disposition"}).issubset(
        ledger.columns
    ):
        raise ValueError("재정 대응표·포함/제외 대장의 필수 열 누락입니다.")
    lookup = lookup.loc[lookup["dataset"] == "fiscal"]
    ledger = ledger.loc[ledger["dataset"] == "fiscal"]
    selected_ledger = ledger.loc[ledger["region_code"].ne("")]
    if (
        lookup.empty
        or lookup[["source_region_code", "region_code"]].eq("").any().any()
        or lookup["source_region_code"].duplicated().any()
        or lookup["region_code"].duplicated().any()
        or ledger["source_region_code"].duplicated().any()
        or set(frame["lafNm"]) != set(ledger["source_region_code"])
        or dict(zip(lookup["source_region_code"], lookup["region_code"]))
        != dict(zip(selected_ledger["source_region_code"], selected_ledger["region_code"]))
    ):
        raise ValueError("재정 원본·대응표·대장의 범위 또는 일대일 매핑이 잘못되었습니다.")
    selected = frame.loc[frame["lafNm"].isin(lookup["source_region_code"])].copy()
    raw_values = selected["firRt"].astype("string").str.strip()
    missing = raw_values.isna() | raw_values.isin(["", "-"])
    numeric = pd.to_numeric(raw_values.mask(missing), errors="coerce")
    observed = numeric.loc[~missing]
    if (
        observed.isna().any()
        or not np.isfinite(observed).all()
        or not observed.between(0, 100).all()
    ):
        raise ValueError("재정자립도에 허용되지 않은 문자열·무한대·범위 밖 값이 있습니다.")
    result = pd.DataFrame(
        {"source_region_code": selected["lafNm"], "fiscal_independence": numeric}
    ).loc[~missing]
    result = result.sort_values("source_region_code").reset_index(drop=True)
    audit = pd.DataFrame(
        {
            "source_region_code": selected["lafNm"],
            "source_value": selected["firRt"],
            "fiscal_independence": numeric,
            "status": np.where(missing, "missing_source_value", "observed"),
        }
    ).merge(lookup[["source_region_code", "region_code"]], validate="one_to_one")
    audit = audit.sort_values("source_region_code")
    details = {
        "status": "fiscal_staging_internal_checks_passed",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "definition_sha256": hashlib.sha256(definition.read_bytes()).hexdigest(),
        "crosswalk_sha256": hashlib.sha256(crosswalk.read_bytes()).hexdigest(),
        "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
        "reference_year": "2025",
        "indicator": "A137 / initial budget / revised definition / general account",
        "year_evidence": "archived request and definition; blank per-record fyr is not a year claim",
        "raw_regions": len(frame),
        "selected_regions": len(selected),
        "excluded_regions": len(frame) - len(selected),
        "observed_regions": len(result),
        "missing_regions": int(missing.sum()),
        "missing_policy": "blank/null/hyphen: omit value row; preserve region in core dataset",
        "note": "비율 합산·평균·대체 없음. 특수지역의 모형 비교 가능성은 후속 검토.",
    }
    for path in [output, report, checks]:
        path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8")
    audit.to_csv(checks, index=False, encoding="utf-8")
    details["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    details["checks_sha256"] = hashlib.sha256(checks.read_bytes()).hexdigest()
    report.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def stage_migration(
    source: Path,
    midyear: Path,
    crosswalk: Path,
    inventory: Path,
    midyear_crosswalk: Path,
    output: Path,
    report: Path,
    checks: Path,
) -> pd.DataFrame:
    """2024 순이동과 연앙인구를 코드 대응 후 같은 연구 지역에 연결한다."""
    with source.open(encoding="cp949", newline="") as handle:
        rows = list(csv.reader(handle))
    items = ["T10", "T20", "T25", "T30", "T31", "T32", "T40", "T50"]
    if (
        len(rows) < 3
        or rows[0] != ["A 행정구역(시군구)별"] + ["Y2024 2024"] * 8
        or len(rows[1]) != 9
        or [label.split(" ")[0] for label in rows[1][1:]] != items
        or any(len(row) != 9 for row in rows[2:])
    ):
        raise ValueError("이동 원본의 2024년 연간 시점·항목·열 구조가 다릅니다.")
    movements = pd.DataFrame(rows[2:], columns=["source_label"] + items)
    movements["source_region_code"] = movements["source_label"].str.extract(
        r"^(\d{2}(?:\d{3})?)\s+", expand=False
    )
    with midyear.open(encoding="cp949", newline="") as handle:
        rows = list(csv.reader(handle))
    if (
        len(rows) < 2
        or rows[0] != ["A 행정구역(시군구)별", "SBB 성별", "YRE 연령별", "Y2024 2024"]
        or any(len(row) != 4 for row in rows[1:])
    ):
        raise ValueError("연앙인구 원본의 2024년 시점·열 구조가 다릅니다.")
    population = pd.DataFrame(rows[1:], columns=["source_label", "sex", "age", "value"])
    if not (population["sex"].eq("0 계") & population["age"].eq("000 계")).all():
        raise ValueError("연앙인구는 성별·연령별 전체 합계만 사용합니다.")
    population["source_region_code"] = population["source_label"].str.extract(
        r"^(\d{2}(?:\d{3})?)\s+", expand=False
    )
    lookup = pd.read_csv(crosswalk, dtype=str, keep_default_na=False)
    ledger = pd.read_csv(inventory, dtype=str, keep_default_na=False)
    midmap = pd.read_csv(midyear_crosswalk, dtype=str, keep_default_na=False)
    required = {"dataset", "source_region_code", "region_code"}
    if not required.issubset(lookup.columns) or not required.issubset(ledger.columns):
        raise ValueError("이동 대응표·대장의 필수 열 누락입니다.")
    if not {"source_region_code", "region_code", "disposition"}.issubset(midmap.columns):
        raise ValueError("연앙인구 대응표의 필수 열 누락입니다.")
    lookup = lookup.loc[lookup["dataset"] == "migration"]
    ledger = ledger.loc[ledger["dataset"] == "migration"]
    selected_ledger = ledger.loc[ledger["region_code"].ne("")]
    selected_midmap = midmap.loc[midmap["region_code"].ne("")]
    for frame, reference in [(movements, ledger), (population, midmap)]:
        if (
            frame["source_region_code"].isna().any()
            or frame["source_region_code"].duplicated().any()
            or reference["source_region_code"].duplicated().any()
            or set(frame["source_region_code"]) != set(reference["source_region_code"])
        ):
            raise ValueError("이동·연앙인구 원본의 코드 누락·중복·미확인 지역입니다.")
    if (
        lookup.empty
        or lookup[["source_region_code", "region_code"]].eq("").any().any()
        or lookup["source_region_code"].duplicated().any()
        or lookup["region_code"].duplicated().any()
        or selected_midmap["region_code"].duplicated().any()
        or dict(zip(lookup["source_region_code"], lookup["region_code"]))
        != dict(zip(selected_ledger["source_region_code"], selected_ledger["region_code"]))
        or set(lookup["region_code"]) != set(selected_midmap["region_code"])
    ):
        raise ValueError("분자·분모의 대상 지역이 다르거나 복수 집계가 매핑되어 있습니다.")
    numerator = movements.merge(
        lookup[["source_region_code", "region_code"]], validate="one_to_one"
    )
    for column in ["T10", "T20", "T25"]:
        text = numerator[column].str.strip()
        if not text.str.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)").all():
            raise ValueError("이동 계수는 누락 없는 정수여야 합니다.")
        numerator[column] = text.str.replace(",", "", regex=False).astype("int64")
    if (numerator[["T10", "T20"]] < 0).any().any() or (
        numerator["T10"] - numerator["T20"] != numerator["T25"]
    ).any():
        raise ValueError("전입·전출 범위 또는 순이동=전입-전출 관계가 잘못되었습니다.")
    denominator = population.merge(
        selected_midmap[["source_region_code", "region_code"]], validate="one_to_one"
    )
    text = denominator["value"].str.strip()
    if not text.str.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?").all():
        raise ValueError("연앙인구에 결측·문자열·음수·무한대가 있습니다.")
    denominator["midyear_population"] = pd.to_numeric(text.str.replace(",", "", regex=False))
    if (
        not np.isfinite(denominator["midyear_population"]).all()
        or (denominator["midyear_population"] <= 0).any()
    ):
        raise ValueError("연앙인구 분모는 유한한 양수여야 합니다.")
    denominator = denominator.rename(columns={"source_region_code": "midyear_source_region_code"})
    joined = numerator.rename(columns={"T25": "net_migrants"}).merge(
        denominator[["region_code", "midyear_source_region_code", "midyear_population"]],
        on="region_code",
        validate="one_to_one",
    )
    joined = joined.sort_values("source_region_code").reset_index(drop=True)
    result = joined[["source_region_code", "net_migrants", "midyear_population"]]
    audit = joined[
        [
            "source_region_code",
            "region_code",
            "midyear_source_region_code",
            "net_migrants",
            "midyear_population",
        ]
    ].copy()
    audit["net_migration_rate"] = 100 * audit["net_migrants"] / audit["midyear_population"]
    if not np.isfinite(audit["net_migration_rate"]).all():
        raise ValueError("순이동률이 유한하지 않습니다.")
    details = {
        "status": "migration_staging_internal_checks_passed",
        "reference_year": "2024",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "midyear_source_sha256": hashlib.sha256(midyear.read_bytes()).hexdigest(),
        "crosswalk_sha256": hashlib.sha256(crosswalk.read_bytes()).hexdigest(),
        "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
        "midyear_crosswalk_sha256": hashlib.sha256(midyear_crosswalk.read_bytes()).hexdigest(),
        "raw_migration_regions": len(movements),
        "raw_midyear_regions": len(population),
        "selected_regions": len(result),
        "missing_regions": 0,
        "net_migrants_total": int(result["net_migrants"].sum()),
        "midyear_population_total": float(result["midyear_population"].sum()),
        "negative_net_regions": int((result["net_migrants"] < 0).sum()),
        "zero_net_regions": int((result["net_migrants"] == 0).sum()),
        "note": "순이동 부호·연앙인구 원값 보존. 거주자 기준 연앙인구 사용; 원본 비율 평균 없음.",
    }
    for path in [output, report, checks]:
        path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8")
    audit.to_csv(checks, index=False, encoding="utf-8")
    details["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    details["checks_sha256"] = hashlib.sha256(checks.read_bytes()).hexdigest()
    report.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="공식 선거·인구·재정·이동 원본 표준화")
    parser.add_argument(
        "--dataset", choices=["election", "population", "fiscal", "migration"], default="election"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--crosswalk", type=Path, default=Path("data/reference/region_crosswalk.csv")
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--inventory", type=Path, default=Path("data/reference/region_source_inventory.csv")
    )
    parser.add_argument("--checks", type=Path)
    parser.add_argument(
        "--definition", type=Path, default=Path("data/raw/lofin365_2025_A137_definition.json")
    )
    parser.add_argument("--midyear-source", type=Path)
    parser.add_argument(
        "--midyear-crosswalk",
        type=Path,
        default=Path("data/reference/midyear_region_crosswalk.csv"),
    )
    args = parser.parse_args()
    if args.dataset == "migration" and args.midyear_source is None:
        parser.error("migration에는 --midyear-source가 필요합니다.")
    output = args.output or Path(f"data/interim/{args.dataset}.csv")
    report = args.report or Path(f"outputs/{args.dataset}_staging_checks.json")
    checks = args.checks or Path(f"outputs/{args.dataset}_staging_checks.csv")
    if args.dataset == "population":
        stage_population(args.source, args.crosswalk, args.inventory, output, report, checks)
    elif args.dataset == "fiscal":
        stage_fiscal(
            args.source, args.crosswalk, args.inventory, args.definition, output, report, checks
        )
    elif args.dataset == "migration":
        stage_migration(
            args.source,
            args.midyear_source,
            args.crosswalk,
            args.inventory,
            args.midyear_crosswalk,
            output,
            report,
            checks,
        )
    else:
        stage_election(args.source, args.crosswalk, output, report)
    print(f"{args.dataset} 표준 입력 생성 완료. 독립 공식 합계 대조는 별도 수행 필요.")


if __name__ == "__main__":
    main()
