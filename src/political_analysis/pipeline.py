"""표준화된 공식 통계를 2025년 연구 분석단위로 결합하고 검증한다.

이 모듈은 원자료 컬럼을 추측해 파싱하지 않는다. CODEBOOK.md에 정의된
표준 CSV와 검증된 지역코드 대응표를 입력으로 받는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from political_analysis.reconciliation import (
    displayed_turnout,
    reconcile_election,
    reported_turnout,
)

DATASETS = ("election", "population", "fiscal", "migration")
CROSSWALK_COLUMNS = (
    "dataset",
    "source_region_code",
    "region_code",
    "region_name",
    "province",
    "region_type",
)
REGION_TYPES = {"시", "군", "자치구", "특수지역"}


def _read_csv(path: Path, required: tuple[str, ...]) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"필요한 데이터 파일이 없습니다: {path}")
    frame = pd.read_csv(
        path,
        dtype={"source_region_code": "string", "region_code": "string"},
        keep_default_na=False,
    )
    absent = sorted(set(required) - set(frame.columns))
    if absent:
        raise ValueError(f"{path}: 필수 컬럼 누락 {absent}")
    if frame.empty:
        raise ValueError(f"{path}: 입력 데이터가 비어 있습니다.")
    for col in (
        "dataset",
        "source_region_code",
        "region_code",
        "region_name",
        "province",
        "region_type",
    ):
        if col in frame:
            frame[col] = frame[col].astype("string").str.strip()
            if frame[col].isna().any() or frame[col].eq("").any():
                raise ValueError(f"{path}: {col}에 빈 값이 있습니다.")
    return frame


def _numeric(
    frame: pd.DataFrame,
    column: str,
    *,
    integer: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    values = pd.to_numeric(frame[column], errors="coerce")
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError(f"{column}: 누락·문자열·무한대가 포함되어 있습니다.")
    if integer and not (values % 1 == 0).all():
        raise ValueError(f"{column}: 정수가 아닌 값이 있습니다.")
    if minimum is not None and (values < minimum).any():
        raise ValueError(f"{column}: 허용 최솟값 {minimum} 미만.")
    if maximum is not None and (values > maximum).any():
        raise ValueError(f"{column}: 허용 최댓값 {maximum} 초과.")
    frame[column] = values.astype("int64" if integer else "float64")


def _read_crosswalk(path: Path) -> pd.DataFrame:
    crosswalk = _read_csv(path, CROSSWALK_COLUMNS)
    if not set(crosswalk["dataset"]).issubset(DATASETS):
        raise ValueError("region_crosswalk: dataset은 4개 표준 데이터셋 중 하나여야 합니다.")
    if not set(crosswalk["region_type"]).issubset(REGION_TYPES):
        raise ValueError("region_crosswalk: region_type은 시/군/자치구/특수지역이어야 합니다.")
    if crosswalk.duplicated(["dataset", "source_region_code"]).any():
        raise ValueError("region_crosswalk: dataset과 source_region_code가 중복됩니다.")
    if crosswalk.duplicated(["region_code", "region_name", "province", "region_type"]).all():
        pass  # 복수 원본 코드가 하나의 분석 지역에 매핑되는 것은 정상.
    meta = crosswalk[list(CROSSWALK_COLUMNS[2:])].drop_duplicates()
    if meta.duplicated("region_code").any():
        raise ValueError("동일 분석 region_code의 지역명·시도·유형이 상충합니다.")
    return crosswalk


def _attach(frame: pd.DataFrame, crosswalk: pd.DataFrame, dataset: str) -> pd.DataFrame:
    lookup = crosswalk.loc[
        crosswalk["dataset"] == dataset,
        ["source_region_code", "region_code"],
    ]
    merged = frame.merge(
        lookup, on="source_region_code", how="left", validate="many_to_one", indicator=True
    )
    unmatched = merged.loc[merged["_merge"] != "both", "source_region_code"].tolist()
    if unmatched:
        raise ValueError(f"{dataset}: 대응되지 않은 원본 지역코드: {unmatched[:15]}")
    return merged.drop(columns="_merge")


def _election(frame: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    if frame.duplicated("source_region_code").any():
        raise ValueError("election: 원본 지역코드 중복. 상위/하위·투표구 집계 혼재를 확인하세요.")
    _numeric(frame, "electors", integer=True, minimum=1)
    _numeric(frame, "voters", integer=True, minimum=0)
    if (frame["voters"] > frame["electors"]).any():
        raise ValueError("election: 선거인수보다 투표자수가 큰 지역이 있습니다.")
    if "reported_turnout" in frame:
        raw = frame["reported_turnout"].astype("string").str.strip()
        claimed = pd.to_numeric(raw.mask(raw.eq("")), errors="coerce")
        if (raw.notna() & raw.ne("") & claimed.isna()).any():
            raise ValueError("reported_turnout: 숫자가 아닌 값이 포함되어 있습니다.")
        if ((claimed.notna()) & (~np.isfinite(claimed.fillna(0)))).any():
            raise ValueError("reported_turnout: 무한대가 포함되어 있습니다.")
        if ((claimed.notna()) & (~claimed.between(0, 100))).any():
            raise ValueError("reported_turnout: 범위 0~100을 벗어났습니다.")
        observed = frame.loc[claimed.notna()]
        if any(
            displayed_turnout(electors, voters) != reported_turnout(str(value))
            for electors, voters, value in zip(
                observed["electors"], observed["voters"], claimed.loc[claimed.notna()]
            )
        ):
            raise ValueError("reported_turnout: 계산값과 표시상 반올림 범위 이상 불일치.")
    merged = _attach(frame, crosswalk, "election")
    return merged.groupby("region_code", as_index=False)[["electors", "voters"]].sum()


def _population(
    frame: pd.DataFrame, crosswalk: pd.DataFrame, expected_ages: list[int] | None = None
) -> pd.DataFrame:
    _numeric(frame, "age", integer=True, minimum=0, maximum=130)
    _numeric(frame, "population", integer=True, minimum=0)
    if frame.duplicated(["source_region_code", "age"]).any():
        raise ValueError("population: 지역코드·연령 중복. 개방연령구간 중복을 확인하세요.")
    if expected_ages is not None:
        expected = set(expected_ages)
        coverage = frame.groupby("source_region_code")["age"].agg(set)
        if any(ages != expected for ages in coverage):
            raise ValueError("population: 원본 계약에 필요한 연령 구간이 누락·추가되었습니다.")
    merged = _attach(frame, crosswalk, "population")
    merged = merged.assign(
        population_total=merged["population"],
        population_18plus=np.where(merged["age"] >= 18, merged["population"], 0),
        population_65plus=np.where(merged["age"] >= 65, merged["population"], 0),
        population_80plus=np.where(merged["age"] >= 80, merged["population"], 0),
    )
    cols = [
        "population_total",
        "population_18plus",
        "population_65plus",
        "population_80plus",
    ]
    out = merged.groupby("region_code", as_index=False)[cols].sum()
    if (out["population_65plus"] <= 0).any():
        raise ValueError("population: 65세 이상 인구가 0인 지역이 있습니다.")
    if (
        (out["population_80plus"] > out["population_65plus"])
        | (out["population_65plus"] > out["population_18plus"])
        | (out["population_18plus"] > out["population_total"])
    ).any():
        raise ValueError("population: 연령별 인구 합계의 포함관계가 잘못되었습니다.")
    return out


def _fiscal(frame: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    if frame.duplicated("source_region_code").any():
        raise ValueError("fiscal: 원본 지역코드 중복입니다.")
    _numeric(frame, "fiscal_independence", minimum=0, maximum=100)
    merged = _attach(frame, crosswalk, "fiscal")
    if merged.duplicated("region_code").any():
        raise ValueError("fiscal: 한 연구지역에 복수 재정자립도 매핑. 비율 합산 금지.")
    return merged[["region_code", "fiscal_independence"]]


def _migration(frame: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    if frame.duplicated("source_region_code").any():
        raise ValueError("migration: 원본 지역코드 중복. 자료 집계 층위를 확인하세요.")
    _numeric(frame, "net_migrants", integer=True)
    _numeric(frame, "midyear_population")
    if (frame["midyear_population"] <= 0).any():
        raise ValueError("migration: 연앙인구는 양수여야 합니다.")
    merged = _attach(frame, crosswalk, "migration")
    return merged.groupby("region_code", as_index=False)[
        ["net_migrants", "midyear_population"]
    ].sum()


def verify_file_hashes(files: dict[str, str]) -> None:
    for name, digest in files.items():
        path = Path(name)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"검증 증거의 파일이 없거나 해시가 변경되었습니다: {path}")


def verify_dataset_certificate(data_path: Path, quality_path: Path) -> dict:
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    if not quality.get("input_contract_verified") or not quality.get(
        "official_election_totals_verified"
    ):
        raise ValueError("입력 계약 또는 공식 선거 합계 검증이 미완료입니다.")
    if hashlib.sha256(data_path.read_bytes()).hexdigest() != quality.get("dataset_sha256"):
        raise ValueError("분석 데이터가 검증된 버전과 다릅니다.")
    if not quality.get("verified_files"):
        raise ValueError("입력·원본 파일의 해시 증거가 없습니다.")
    verify_file_hashes(quality["verified_files"])
    return quality


def _staging_contract(
    input_dir: Path, crosswalk_path: Path, expected_path: Path, reports_dir: Path
) -> tuple[dict[str, str], list[int], Path]:
    """스테이징의 입력/출력 해시를 실제 보존 원본까지 연결한다."""
    root = input_dir.resolve().parent
    raw_hashes = {}
    for path in sorted((root / "raw").iterdir()):
        if path.is_file():
            raw_hashes.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), path)
    files = {}

    def require(path: Path, digest: str) -> None:
        name = str(path.resolve())
        verify_file_hashes({name: digest})
        files[name] = digest

    for path in [crosswalk_path, expected_path]:
        require(path, hashlib.sha256(path.read_bytes()).hexdigest())
    age_contract = None
    election_source = None
    source_fields = {
        "election": ["source_sha256"],
        "population": ["source_sha256"],
        "fiscal": ["source_sha256", "definition_sha256"],
        "migration": ["source_sha256", "midyear_source_sha256"],
    }
    for dataset in DATASETS:
        path = reports_dir / f"{dataset}_staging_checks.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence.get("status") != f"{dataset}_staging_internal_checks_passed":
            raise ValueError(f"{dataset}: 스테이징 검사 상태가 유효하지 않습니다.")
        require(path, hashlib.sha256(path.read_bytes()).hexdigest())
        require(input_dir / f"{dataset}.csv", evidence["output_sha256"])
        require(crosswalk_path, evidence["crosswalk_sha256"])
        for field in source_fields[dataset]:
            digest = evidence[field]
            if digest not in raw_hashes:
                raise ValueError(f"{dataset}: 필요한 해시의 원본이 없거나 변경되었습니다.")
            require(raw_hashes[digest], digest)
        if dataset == "election":
            election_source = raw_hashes[evidence["source_sha256"]]
        if "inventory_sha256" in evidence:
            require(root / "reference/region_source_inventory.csv", evidence["inventory_sha256"])
        if "midyear_crosswalk_sha256" in evidence:
            require(
                root / "reference/midyear_region_crosswalk.csv",
                evidence["midyear_crosswalk_sha256"],
            )
        if "checks_sha256" in evidence:
            require(reports_dir / f"{dataset}_staging_checks.csv", evidence["checks_sha256"])
        if dataset == "population":
            age_contract = evidence["expected_ages"]
            if (
                not age_contract
                or len(set(age_contract)) != len(age_contract)
                or any(type(age) is not int or not 0 <= age <= 130 for age in age_contract)
            ):
                raise ValueError("population: 스테이징 연령 계약이 유효하지 않습니다.")
    mapping_path = reports_dir / "region_mapping_checks.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if mapping.get("status") != "region_reference_structure_verified":
        raise ValueError("지역 참조자료 검증이 미완료입니다.")
    require(mapping_path, hashlib.sha256(mapping_path.read_bytes()).hexdigest())
    for name, digest in mapping["hashes"].items():
        require(root.parent / name, digest)
    if str(expected_path.resolve()) not in {
        str((root.parent / name).resolve()) for name in mapping["hashes"]
    }:
        raise ValueError("독립 기대 지역 명부가 참조자료 검증에 포함되지 않았습니다.")
    return files, age_contract, election_source


def build_dataset(
    input_dir: Path,
    crosswalk_path: Path,
    output_path: Path,
    report_path: Path,
    *,
    expected_regions_path: Path | None = None,
    staging_reports_dir: Path | None = None,
    official_election_zip: Path | None = None,
    reconciliation_output_path: Path | None = None,
) -> pd.DataFrame:
    """핵심 인구·선거 관측치를 완전 결합하고 통제변수 누락을 보고한다."""
    crosswalk = _read_crosswalk(crosswalk_path)
    metadata = crosswalk[
        ["region_code", "region_name", "province", "region_type"]
    ].drop_duplicates()
    expected = metadata
    if expected_regions_path is not None:
        expected = _read_csv(expected_regions_path, tuple(metadata.columns))
        if expected["region_code"].duplicated().any() or set(
            expected[list(metadata.columns)].itertuples(index=False, name=None)
        ) != set(metadata.itertuples(index=False, name=None)):
            raise ValueError("독립 기대 지역 명부와 대응표의 코드·메타데이터가 다릅니다.")
    lineage = {}
    expected_ages = None
    election_source = None
    if staging_reports_dir is not None:
        if expected_regions_path is None:
            raise ValueError("스테이징 검증에는 독립 기대 지역 명부가 필요합니다.")
        lineage, expected_ages, election_source = _staging_contract(
            input_dir, crosswalk_path, expected_regions_path, staging_reports_dir
        )
    required = {
        "election": ("source_region_code", "electors", "voters"),
        "population": ("source_region_code", "age", "population"),
        "fiscal": ("source_region_code", "fiscal_independence"),
        "migration": ("source_region_code", "net_migrants", "midyear_population"),
    }
    inputs = {key: _read_csv(input_dir / f"{key}.csv", cols) for key, cols in required.items()}
    for name in ["election", "population"]:
        declared = set(crosswalk.loc[crosswalk["dataset"] == name, "source_region_code"])
        actual = set(inputs[name]["source_region_code"])
        if actual - declared:
            raise ValueError(f"{name}: 대응되지 않은 원본 지역코드가 있습니다.")
        if declared - actual:
            raise ValueError(f"{name}: 원본 지역 누락이 있습니다.")
    election = _election(inputs["election"], crosswalk)
    population = _population(inputs["population"], crosswalk, expected_ages)
    fiscal = _fiscal(inputs["fiscal"], crosswalk)
    migration = _migration(inputs["migration"], crosswalk)

    joined = election.merge(
        population, on="region_code", how="outer", validate="one_to_one", indicator=True
    )
    if (joined["_merge"] != "both").any():
        diff = joined.loc[joined["_merge"] != "both", ["region_code", "_merge"]]
        raise ValueError(f"선거/인구 지역 단위 불일치: {diff.to_dict('records')[:20]}")
    joined = joined.drop(columns="_merge")
    if set(joined["region_code"]) != set(expected["region_code"]):
        raise ValueError("결합한 핵심 자료와 기대 지역 집합이 다릅니다.")
    joined = joined.merge(fiscal, how="left", on="region_code", validate="one_to_one")
    joined = joined.merge(migration, how="left", on="region_code", validate="one_to_one")

    joined = joined.merge(metadata, how="left", on="region_code", validate="one_to_one")
    if joined[["region_name", "province", "region_type"]].isna().any().any():
        raise ValueError("지역 메타데이터 누락이 발생했습니다.")

    joined["turnout"] = 100 * joined["voters"] / joined["electors"]
    joined["aging_rate"] = 100 * (joined["population_65plus"] / joined["population_18plus"])
    joined["oldest_share"] = 100 * (joined["population_80plus"] / joined["population_65plus"])
    joined["net_migration_rate"] = 100 * (joined["net_migrants"] / joined["midyear_population"])
    joined["log_population"] = np.log(joined["population_total"])
    for column in ["turnout", "aging_rate", "oldest_share", "net_migration_rate", "log_population"]:
        if not np.isfinite(joined[column].dropna()).all():
            raise ValueError(f"{column}: 유한하지 않은 파생변수가 있습니다.")

    if (
        (joined["turnout"] < 0)
        | (joined["turnout"] > 100)
        | (joined["aging_rate"] < 0)
        | (joined["aging_rate"] > 100)
        | (joined["oldest_share"] < 0)
        | (joined["oldest_share"] > 100)
    ).any():
        raise ValueError("핵심 파생변수가 백분율의 허용범위를 벗어났습니다.")

    fields = [
        "region_code",
        "region_name",
        "province",
        "region_type",
        "electors",
        "voters",
        "turnout",
        "population_total",
        "population_18plus",
        "population_65plus",
        "population_80plus",
        "aging_rate",
        "oldest_share",
        "fiscal_independence",
        "net_migrants",
        "midyear_population",
        "net_migration_rate",
        "log_population",
    ]
    result = joined[fields].sort_values("region_code").reset_index(drop=True)
    reconciliation = {}
    if official_election_zip is not None:
        if election_source is None or reconciliation_output_path is None:
            raise ValueError("공식 대조에는 검증된 원본과 대조표 경로가 필요합니다.")
        reconciliation = reconcile_election(
            inputs["election"],
            crosswalk,
            election_source,
            official_election_zip,
            reconciliation_output_path,
        )
        lineage[str(official_election_zip.resolve())] = reconciliation["official_zip_sha256"]
        lineage[str(reconciliation_output_path.resolve())] = reconciliation["reconciliation_sha256"]
    if lineage:
        for name in ["pipeline.py", "reconciliation.py", "staging.py"]:
            path = Path(__file__).with_name(name).resolve()
            lineage[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {
        "status": "standardized_inputs_validated",
        "official_election_totals_verified": bool(reconciliation),
        "input_contract_verified": bool(lineage and expected_ages is not None),
        "population_age_coverage_verified": expected_ages is not None,
        "reconciliation": reconciliation,
        "study": "2025 presidential election and subnational aging",
        "observations": int(len(result)),
        "raw_input_rows": {name: int(len(frame)) for name, frame in inputs.items()},
        "totals": {
            "electors": int(result["electors"].sum()),
            "voters": int(result["voters"].sum()),
        },
        "missing_by_column": {column: int(result[column].isna().sum()) for column in fields},
        "caveat": (
            "표준화된 CSV의 내부 일관성만 검사함. "
            "공식 원본 집계범위/해외·사전투표 귀속 및 공식 합계는 수동 검증 필요."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    report["dataset_sha256"] = hashlib.sha256(output_path.read_bytes()).hexdigest()
    lineage[str(output_path.resolve())] = report["dataset_sha256"]
    report["verified_files"] = lineage
    if reconciliation:
        report["status"] = "input_contracts_and_official_totals_verified"
        report["caveat"] = reconciliation["note"]
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="연구용 지역 통합 데이터셋 생성")
    parser.add_argument("--input-dir", type=Path, default=Path("data/interim"))
    parser.add_argument(
        "--crosswalk", type=Path, default=Path("data/reference/region_crosswalk.csv")
    )
    parser.add_argument("--output", type=Path, default=Path("data/processed/analysis_dataset.csv"))
    parser.add_argument("--report", type=Path, default=Path("outputs/data_quality.json"))
    parser.add_argument(
        "--expected-regions", type=Path, default=Path("data/reference/expected_regions.csv")
    )
    parser.add_argument("--staging-reports-dir", type=Path, default=Path("outputs"))
    parser.add_argument(
        "--official-election-zip",
        type=Path,
        default=Path("data/raw/제21대 대통령선거 투표율 분석.zip"),
    )
    parser.add_argument(
        "--reconciliation-output", type=Path, default=Path("outputs/official_reconciliation.csv")
    )
    args = parser.parse_args()
    result = build_dataset(
        args.input_dir,
        args.crosswalk,
        args.output,
        args.report,
        expected_regions_path=args.expected_regions,
        staging_reports_dir=args.staging_reports_dir,
        official_election_zip=args.official_election_zip,
        reconciliation_output_path=args.reconciliation_output,
    )
    print(f"{len(result)}개 지역 입력·공식 합계 검증 완료. 지역별 조정은 독립 재검증과 구별함.")


if __name__ == "__main__":
    main()
