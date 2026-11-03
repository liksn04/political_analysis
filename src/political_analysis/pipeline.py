"""표준화된 공식 통계를 2025년 연구 분석단위로 결합하고 검증한다.

이 모듈은 원자료 컬럼을 추측해 파싱하지 않는다. CODEBOOK.md에 정의된
표준 CSV와 검증된 지역코드 대응표를 입력으로 받는다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

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
    frame = pd.read_csv(path, dtype={"source_region_code": "string", "region_code": "string"})
    absent = sorted(set(required) - set(frame.columns))
    if absent:
        raise ValueError(f"{path}: 필수 컬럼 누락 {absent}")
    if frame.empty:
        raise ValueError(f"{path}: 입력 데이터가 비어 있습니다.")
    for col in ("dataset", "source_region_code", "region_code", "region_name",
                "province", "region_type"):
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


def _attach(
    frame: pd.DataFrame, crosswalk: pd.DataFrame, dataset: str
) -> pd.DataFrame:
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
        claimed = pd.to_numeric(frame["reported_turnout"], errors="coerce")
        if ((claimed.notna()) & (~np.isfinite(claimed.fillna(0)))).any():
            raise ValueError("reported_turnout: 무한대가 포함되어 있습니다.")
        if ((claimed.notna()) & (~claimed.between(0, 100))).any():
            raise ValueError("reported_turnout: 범위 0~100을 벗어났습니다.")
        computed = 100 * frame["voters"] / frame["electors"]
        if ((claimed.notna()) & ((claimed - computed).abs() > 0.11)).any():
            raise ValueError("reported_turnout: 계산값과 표시상 반올림 범위 이상 불일치.")
    merged = _attach(frame, crosswalk, "election")
    return merged.groupby("region_code", as_index=False)[["electors", "voters"]].sum()


def _population(frame: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    _numeric(frame, "age", integer=True, minimum=0, maximum=130)
    _numeric(frame, "population", integer=True, minimum=0)
    if frame.duplicated(["source_region_code", "age"]).any():
        raise ValueError("population: 지역코드·연령 중복. 개방연령구간 중복을 확인하세요.")
    merged = _attach(frame, crosswalk, "population")
    merged = merged.assign(
        population_total=merged["population"],
        population_18plus=np.where(merged["age"] >= 18, merged["population"], 0),
        population_65plus=np.where(merged["age"] >= 65, merged["population"], 0),
        population_80plus=np.where(merged["age"] >= 80, merged["population"], 0),
    )
    cols = [
        "population_total", "population_18plus",
        "population_65plus", "population_80plus",
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
    _numeric(frame, "midyear_population", minimum=1)
    merged = _attach(frame, crosswalk, "migration")
    return merged.groupby("region_code", as_index=False)[
        ["net_migrants", "midyear_population"]
    ].sum()


def build_dataset(
    input_dir: Path, crosswalk_path: Path, output_path: Path, report_path: Path
) -> pd.DataFrame:
    """핵심 인구·선거 관측치를 완전 결합하고 통제변수 누락을 보고한다."""
    crosswalk = _read_crosswalk(crosswalk_path)
    required = {
        "election": ("source_region_code", "electors", "voters"),
        "population": ("source_region_code", "age", "population"),
        "fiscal": ("source_region_code", "fiscal_independence"),
        "migration": ("source_region_code", "net_migrants", "midyear_population"),
    }
    inputs = {
        key: _read_csv(input_dir / f"{key}.csv", cols)
        for key, cols in required.items()
    }
    election = _election(inputs["election"], crosswalk)
    population = _population(inputs["population"], crosswalk)
    fiscal = _fiscal(inputs["fiscal"], crosswalk)
    migration = _migration(inputs["migration"], crosswalk)

    joined = election.merge(
        population, on="region_code", how="outer", validate="one_to_one", indicator=True
    )
    if (joined["_merge"] != "both").any():
        diff = joined.loc[joined["_merge"] != "both", ["region_code", "_merge"]]
        raise ValueError(f"선거/인구 지역 단위 불일치: {diff.to_dict('records')[:20]}")
    joined = joined.drop(columns="_merge")
    joined = joined.merge(fiscal, how="left", on="region_code", validate="one_to_one")
    joined = joined.merge(migration, how="left", on="region_code", validate="one_to_one")

    metadata = crosswalk[
        ["region_code", "region_name", "province", "region_type"]
    ].drop_duplicates()
    joined = joined.merge(metadata, how="left", on="region_code", validate="one_to_one")
    if joined[["region_name", "province", "region_type"]].isna().any().any():
        raise ValueError("지역 메타데이터 누락이 발생했습니다.")

    joined["turnout"] = 100 * joined["voters"] / joined["electors"]
    joined["aging_rate"] = 100 * (
        joined["population_65plus"] / joined["population_18plus"]
    )
    joined["oldest_share"] = 100 * (
        joined["population_80plus"] / joined["population_65plus"]
    )
    joined["net_migration_rate"] = 100 * (
        joined["net_migrants"] / joined["midyear_population"]
    )
    joined["log_population"] = np.log(joined["population_total"])

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
        "region_code", "region_name", "province", "region_type",
        "electors", "voters", "turnout",
        "population_total", "population_18plus",
        "population_65plus", "population_80plus",
        "aging_rate", "oldest_share", "fiscal_independence",
        "net_migrants", "midyear_population", "net_migration_rate", "log_population",
    ]
    result = joined[fields].sort_values("region_code").reset_index(drop=True)
    report = {
        "status": "standardized_inputs_validated",
        "official_election_totals_verified": False,
        "study": "2025 presidential election and subnational aging",
        "observations": int(len(result)),
        "raw_input_rows": {name: int(len(frame)) for name, frame in inputs.items()},
        "totals": {
            "electors": int(result["electors"].sum()),
            "voters": int(result["voters"].sum()),
        },
        "missing_by_column": {
            column: int(result[column].isna().sum())
            for column in fields
        },
        "caveat": (
            "표준화된 CSV의 내부 일관성만 검사함. "
            "공식 원본 집계범위/해외·사전투표 귀속 및 공식 합계는 수동 검증 필요."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
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
    parser.add_argument(
        "--output", type=Path, default=Path("data/processed/analysis_dataset.csv")
    )
    parser.add_argument("--report", type=Path, default=Path("outputs/data_quality.json"))
    args = parser.parse_args()
    result = build_dataset(args.input_dir, args.crosswalk, args.output, args.report)
    print(f"내부 검증 완료: {len(result)}개 지역. 공식 원본 합계 대조는 별도 수행 필요.")


if __name__ == "__main__":
    main()
