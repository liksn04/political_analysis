"""지역 단위 회귀모형과 재현 가능한 통계·그림 결과 생성."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from political_analysis.exploration import run_exploration
from political_analysis.pipeline import REGION_TYPES, verify_dataset_certificate

FORMULAS = {
    "M1": "turnout ~ aging_rate",
    "M2": "turnout ~ aging_rate + oldest_share",
    "M3": (
        "turnout ~ aging_rate + oldest_share + fiscal_independence"
        " + net_migration_rate + log_population"
    ),
    "M4": (
        "turnout ~ aging_rate + oldest_share + fiscal_independence"
        " + net_migration_rate + log_population + C(region_type) + C(province)"
    ),
}
COVARIATES = [
    "turnout", "aging_rate", "oldest_share", "fiscal_independence",
    "net_migration_rate", "log_population", "region_type", "province", "electors",
]


MODEL_VARIABLES = {
    "M1": ["turnout", "aging_rate"],
    "M2": ["turnout", "aging_rate", "oldest_share"],
    "M3": [
        "turnout",
        "aging_rate",
        "oldest_share",
        "fiscal_independence",
        "net_migration_rate",
        "log_population",
    ],
    "M4": [
        "turnout",
        "aging_rate",
        "oldest_share",
        "fiscal_independence",
        "net_migration_rate",
        "log_population",
        "region_type",
        "province",
    ],
}


def fit_models_with_samples(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """추정표와 모든 입력 행의 모형별 포함/제외 사유를 함께 반환한다."""
    missing = set(COVARIATES) - set(data.columns)
    if missing:
        raise ValueError(f"분석 컬럼 누락: {sorted(missing)}")
    if data.empty:
        raise ValueError("분석 파일이 비어 있습니다.")
    data = data.copy().reset_index(drop=True)
    numeric = MODEL_VARIABLES["M3"] + ["electors"]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column].dropna()).all():
            raise ValueError(f"{column}: 무한대가 있습니다.")
    if (data["electors"].dropna() <= 0).any():
        raise ValueError("선거인수는 양수여야 합니다.")
    for column in ["region_type", "province"]:
        values = data[column].astype("string").str.strip()
        data[column] = values.mask(values.eq(""))
    if not set(data["region_type"].dropna()).issubset(REGION_TYPES):
        raise ValueError("허용되지 않은 지역 유형입니다.")
    if "region_code" in data:
        ids = data["region_code"].astype("string").str.strip()
        if ids.isna().any() or ids.eq("").any() or ids.duplicated().any():
            raise ValueError("region_code는 누락·중복 없는 식별자여야 합니다.")
        id_kind = "region_code"
    else:
        ids = pd.Series([f"row_{i}" for i in data.index])
        id_kind = "row_position_synthetic_or_in_memory"

    common_mask = data[MODEL_VARIABLES["M4"]].notna().all(axis=1) & data["region_type"].ne(
        "특수지역"
    ).fillna(False)
    coefficients, summaries, samples = [], [], []
    specifications = [(name, name, False, False) for name in FORMULAS]
    specifications += [("M4_WLS", "M4", True, False)]
    specifications += [(name + "_common", name, False, True) for name in ["M1", "M2", "M3"]]
    for name, base, weighted, common in specifications:
        variables = MODEL_VARIABLES[base] + (["electors"] if weighted else [])
        eligibility_variables = MODEL_VARIABLES["M4"] if common else variables
        complete = data[eligibility_variables].notna().all(axis=1)
        special_policy = base == "M4" or common
        special = data["region_type"].eq("특수지역").fillna(False)
        mask = common_mask.copy() if common else complete & (~special if special_policy else True)
        subset = data.loc[mask].copy()
        if subset.empty:
            raise ValueError(f"{name}: 완전 사례 표본이 없습니다.")
        references = {}
        if base == "M4":
            for column in ["region_type", "province"]:
                levels = sorted(subset[column].astype(str).unique())
                references[column] = levels[0]
                subset[column] = pd.Categorical(subset[column].astype(str), categories=levels)
        if weighted:
            model = smf.wls(
                FORMULAS[base], data=subset, weights=subset["electors"], missing="raise"
            )
        else:
            model = smf.ols(FORMULAS[base], data=subset, missing="raise")
        x = np.asarray(model.wexog, dtype=float)
        n, p = x.shape
        if n != int(mask.sum()) or not np.isfinite(x).all() or not np.isfinite(model.endog).all():
            raise ValueError(f"{name}: 설계행렬·표본 또는 유한값 계약이 잘못되었습니다.")
        if n <= p:
            raise ValueError(f"{name}: 관측치가 회귀변수 수보다 충분히 많지 않습니다.")
        rank = int(np.linalg.matrix_rank(x))
        if rank != p:
            raise ValueError(f"{name}: 설계행렬이 완전 공선성으로 식별되지 않습니다.")
        if np.ptp(model.endog) == 0:
            raise ValueError(f"{name}: 종속변수가 상수입니다.")
        q, _ = np.linalg.qr(x, mode="reduced")
        leverage = np.square(q).sum(axis=1)
        if (1 - leverage <= 1e-12).any():
            raise ValueError(f"{name}: leverage가 1에 가까워 HC3를 정의할 수 없습니다.")
        fitted = model.fit(cov_type="HC3", use_t=False)
        ci = fitted.conf_int(alpha=0.05)
        reported = np.concatenate(
            [
                fitted.params,
                fitted.bse,
                fitted.pvalues,
                ci.to_numpy().ravel(),
                [fitted.rsquared, fitted.rsquared_adj],
            ]
        )
        if not np.isfinite(reported).all():
            raise ValueError(f"{name}: 유한하지 않은 추정 결과입니다.")
        for term in fitted.params.index:
            coefficients.append(
                {
                    "model": name,
                    "term": term,
                    "estimate": float(fitted.params[term]),
                    "std_error_hc3": float(fitted.bse[term]),
                    "p_value": float(fitted.pvalues[term]),
                    "ci_low": float(ci.loc[term, 0]),
                    "ci_high": float(ci.loc[term, 1]),
                }
            )
        summaries.append(
            {
                "model": name,
                "n": int(fitted.nobs),
                "r_squared": float(fitted.rsquared),
                "adj_r_squared": float(fitted.rsquared_adj),
                "covariance": "HC3",
                "ci_distribution": "normal",
                "formula": FORMULAS[base],
                "candidates": len(data),
                "excluded": len(data) - n,
                "design_columns": json.dumps(model.exog_names, ensure_ascii=False),
                "design_rank": rank,
                "parameters": p,
                "df_resid": float(fitted.df_resid),
                "condition_number": float(np.linalg.cond(x)),
                "max_leverage": float(leverage.max()),
                "sample_id_kind": id_kind,
                "region_type_reference": references.get("region_type", ""),
                "province_reference": references.get("province", ""),
            }
        )
        for position, row in data.iterrows():
            reasons = []
            if special_policy and special.loc[position]:
                reasons.append("special_region_policy")
            absent = [col for col in eligibility_variables if pd.isna(row[col])]
            if absent:
                reasons.append("missing:" + ",".join(absent))
            if common and not mask.loc[position]:
                reasons.insert(0, "outside_M4_common_sample")
            samples.append(
                {
                    "model": name,
                    "sample_id": str(ids.loc[position]),
                    "row_position": position,
                    "region_name": row.get("region_name", ""),
                    "province": row["province"],
                    "region_type": row["region_type"],
                    "included": bool(mask.loc[position]),
                    "exclusion_reason": ";".join(reasons),
                }
            )
    return pd.DataFrame(coefficients), pd.DataFrame(summaries), pd.DataFrame(samples)


def fit_models(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """기존 2개 반환값 API를 유지한다. 상세 실행은 표본 명단도 반환한다."""
    coefficients, summary, _ = fit_models_with_samples(data)
    return coefficients, summary


def run_analysis(
    data_path: Path, output_dir: Path, quality_path: Path = Path("outputs/data_quality.json")
) -> None:
    if not data_path.is_file():
        raise FileNotFoundError(
            f"{data_path} 없음. 먼저 공식 자료 수집 및 make build를 완료하세요."
        )
    certificate = verify_dataset_certificate(data_path, quality_path)
    frame = pd.read_csv(data_path, dtype={"region_code": "string"})
    coefficients, summary, samples = fit_models_with_samples(frame)
    tables = output_dir / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    coefficients.to_csv(tables / "model_coefficients.csv", index=False)
    summary.to_csv(tables / "model_summary.csv", index=False)
    samples.to_csv(tables / "model_samples.csv", index=False)

    run_exploration(data_path, output_dir, quality_path)

    notes = [
        "2025 presidential election / cross-sectional regional association",
        "M1/M2: 기초표본, M3: 통제변수 관측 가능 지역",
        "M4: 지역유형·시도 고정효과, 특수지역 제외",
        "M4_WLS: 선거인수 가중치·HC3, 특수지역 제외",
        "M1_common~M3_common: M4와 동일한 완전 사례 표본",
        "모든 회귀분석: HC3 표준오차, 정규근사 양측 95% CI (use_t=False)",
        "모형별 포함/제외 명단·사유는 model_samples.csv, 설계·기준범주는 model_summary.csv",
        "모형별 관측치(n)는 model_summary.csv에서 확인",
        "이 통계는 인과효과 또는 개인별 투표행동을 입증하지 않음.",
        "시도 고정효과가 모든 미측정 지역특성을 통제하지 않음.",
        "공식 대조 범위는 data_quality.json 참조; 지역별 범위 조정은 독립 재검증과 구별함.",
        "VIF·영향점·공간의존성 및 가중치 감도분석은 별도 검토 필요.",
    ]
    (output_dir / "model_notes.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    artifacts = [
        tables / "model_coefficients.csv",
        tables / "model_summary.csv",
        tables / "model_samples.csv",
        output_dir / "model_notes.txt",
    ]
    manifest = {
        "status": "model_outputs_generated",
        "dataset_sha256": certificate["dataset_sha256"],
        "quality_sha256": hashlib.sha256(quality_path.read_bytes()).hexdigest(),
        "model_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "models": summary["model"].tolist(),
        "artifacts": {
            str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifacts
        },
        "note": "HC3 normal CI; model-specific sample policy and exclusions are reported separately.",
    }
    (output_dir / "model_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"회귀분석 완료. 산출물: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="지역 고령화·투표율 회귀분석")
    parser.add_argument("--data", type=Path, default=Path("data/processed/analysis_dataset.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--quality-report", type=Path, default=Path("outputs/data_quality.json"))
    args = parser.parse_args()
    run_analysis(args.data, args.output_dir, args.quality_report)


if __name__ == "__main__":
    main()
