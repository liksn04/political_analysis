"""지역 단위 회귀모형과 재현 가능한 통계·그림 결과 생성."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

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


def fit_models(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """M1~M4 및 M4의 선거인수 가중 강건성 분석.

    M4/WLS는 특수지역을 제외한다. 기타 모형은 관측 가능한 모든 지역을
    사용하므로 모형별 n 차이를 반드시 함께 보고해야 한다.
    """
    missing = set(COVARIATES) - set(data.columns)
    if missing:
        raise ValueError(f"분석 컬럼 누락: {sorted(missing)}")
    if data.empty:
        raise ValueError("분석 파일이 비어 있습니다.")
    data = data.copy()
    if (data["electors"].dropna() <= 0).any():
        raise ValueError("선거인수는 양수여야 합니다.")

    fits = {}
    for name, formula in FORMULAS.items():
        subset = data
        if name == "M4":
            subset = data.loc[data["region_type"] != "특수지역"]
        model = smf.ols(formula, data=subset, missing="drop")
        if model.exog.shape[0] <= model.exog.shape[1]:
            raise ValueError(f"{name}: 관측치가 회귀변수 수보다 충분히 많지 않습니다.")
        fits[name] = model.fit(cov_type="HC3")

    weighted = data.loc[data["region_type"] != "특수지역"]
    wls = smf.wls(
        FORMULAS["M4"], data=weighted, weights=weighted["electors"],
        missing="drop",
    )
    if wls.exog.shape[0] <= wls.exog.shape[1]:
        raise ValueError("M4_WLS: 관측치가 충분하지 않습니다.")
    fits["M4_WLS"] = wls.fit(cov_type="HC3")

    # 동일 표본으로 다시 추정하여 표본 변화와 통제변수 효과를 구분할 수 있도록 한다.
    common = data.loc[data["region_type"] != "특수지역"].dropna(subset=COVARIATES)
    for name in ("M1", "M2", "M3"):
        model = smf.ols(FORMULAS[name], data=common)
        if model.exog.shape[0] <= model.exog.shape[1]:
            raise ValueError(f"{name}_common: 공통표본이 너무 작습니다.")
        fits[f"{name}_common"] = model.fit(cov_type="HC3")

    coefficients = []
    summaries = []
    for name, model in fits.items():
        ci = model.conf_int(alpha=0.05)
        for term in model.params.index:
            coefficients.append(
                {
                    "model": name,
                    "term": term,
                    "estimate": float(model.params[term]),
                    "std_error_hc3": float(model.bse[term]),
                    "p_value": float(model.pvalues[term]),
                    "ci_low": float(ci.loc[term, 0]),
                    "ci_high": float(ci.loc[term, 1]),
                }
            )
        summaries.append(
            {
                "model": name,
                "n": int(model.nobs),
                "r_squared": float(model.rsquared),
                "adj_r_squared": float(model.rsquared_adj),
                "covariance": "HC3",
            }
        )
    return pd.DataFrame(coefficients), pd.DataFrame(summaries)


def run_analysis(data_path: Path, output_dir: Path) -> None:
    if not data_path.is_file():
        raise FileNotFoundError(
            f"{data_path} 없음. 먼저 공식 자료 수집 및 make build를 완료하세요."
        )
    frame = pd.read_csv(data_path, dtype={"region_code": "string"})
    coefficients, summary = fit_models(frame)
    tables = output_dir / "tables"
    figures = output_dir / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    coefficients.to_csv(tables / "model_coefficients.csv", index=False)
    summary.to_csv(tables / "model_summary.csv", index=False)

    descriptive = frame.select_dtypes(include="number").describe().transpose()
    descriptive.to_csv(tables / "descriptive_statistics.csv")
    correlation = frame[["turnout", "aging_rate", "oldest_share"]].corr(method="pearson")
    correlation.to_csv(tables / "correlations.csv")

    scatter = frame[["aging_rate", "turnout"]].dropna().sort_values("aging_rate")
    if len(scatter) >= 3 and scatter["aging_rate"].nunique() > 1:
        x = scatter["aging_rate"].to_numpy(dtype=float)
        y = scatter["turnout"].to_numpy(dtype=float)
        slope, intercept = np.polyfit(x, y, deg=1)
        fig, ax = plt.subplots(figsize=(7.5, 5.2))
        ax.scatter(x, y, alpha=0.65, s=28)
        ax.plot(x, slope * x + intercept, linewidth=1.8)
        ax.set_xlabel("65+ / 18+ population (%)")
        ax.set_ylabel("Turnout (%)")
        ax.set_title("2025 presidential election: aging and turnout")
        fig.tight_layout()
        fig.savefig(figures / "scatter_aging_turnout.png", dpi=180)
        plt.close(fig)

    notes = [
        "2025 presidential election / cross-sectional regional association",
        "M1/M2: 기초표본, M3: 통제변수 관측 가능 지역",
        "M4: 지역유형·시도 고정효과, 특수지역 제외",
        "M4_WLS: 선거인수 가중치·HC3, 특수지역 제외",
        "M1_common~M3_common: M4와 동일한 완전 사례 표본",
        "모든 회귀분석: 이분산 강건 HC3 표준오차, 양측 95% CI",
        "모형별 관측치(n)는 model_summary.csv에서 확인",
        "이 통계는 인과효과 또는 개인별 투표행동을 입증하지 않음.",
        "시도 고정효과가 모든 미측정 지역특성을 통제하지 않음.",
        "최종 보고 전 공식 집계 대조, VIF, 영향점, 공간의존성 검토 필요.",
    ]
    (output_dir / "model_notes.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    print(f"회귀분석 완료. 산출물: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="지역 고령화·투표율 회귀분석")
    parser.add_argument(
        "--data", type=Path, default=Path("data/processed/analysis_dataset.csv")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    run_analysis(args.data, args.output_dir)


if __name__ == "__main__":
    main()
