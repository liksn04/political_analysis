"""사전 계획 외 탐색 분석: 지역 투표율을 나이 구성과 같은 나이대 차이로 나눈다 (ADR-014).

주 계산은 전수 자료(실제 투표율, 주민등록 인구)와 전국 연령대 투표율만 쓴다. 표본이 투표구
단위 군집이므로 지역별 표본값은 격차와 직접 표준화 같은 보조 지표에만 쓴다. H1·H2 판정은
기본 M4를 따르며 이 모듈의 결과로 바꾸지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from decimal import InvalidOperation
from pathlib import Path
from zipfile import ZipFile

import matplotlib
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from political_analysis.models import FORMULAS
from political_analysis.pipeline import verify_dataset_certificate
from political_analysis.reconciliation import _count, _sheet_rows

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

AGE_MEMBER = "01_투표율분석결과(표본)/11-성별·연령대별 투표율(구시군별).xlsx"
AGE_SHEETS = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)
BAND_COLUMNS = {
    "E": "18세", "F": "19세", "G": "20-24세", "H": "25-29세", "I": "30-34세", "J": "35-39세",
    "K": "40-49세", "L": "50-59세", "M": "60-69세", "N": "70-79세", "O": "80세이상",
}
BANDS = (
    "18", "19", "20-24", "25-29", "30-34", "35-39", "40-49", "50-59", "60-69", "70-79", "80+",
)
AGE_EDGES = (18, 19, 20, 25, 30, 35, 40, 50, 60, 70, 80, 131)
SPECIFICATIONS = (
    ("M1_common", "M1", False),
    ("M2_common", "M2", False),
    ("M3_common", "M3", False),
    ("M4", "M4", False),
    ("M4_WLS", "M4", True),
)
COMPONENTS = {
    "actual": "turnout",
    "composition": "composition_expected",
    "within_age": "within_age_difference",
}
HONAM = ("광주광역시", "전라남도", "전북특별자치도")
DESIGN_EFFECTS = (1, 2, 4)
Z_95 = 1.959963984540054
TOLERANCE = 1e-8
COLOR_MAIN = "#2a78d6"
COLOR_ACCENT = "#eb6834"
COLOR_REFERENCE = "#8a8983"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _cell(row: dict, column: str) -> int:
    try:
        return _count(str(row.get(column, "")).strip())
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"표본 표의 계수가 잘못되었습니다: {row.get('_row')}행 {column}열") from error


def _row_counts(row: dict) -> tuple[int, dict[str, int]]:
    counts = {band: _cell(row, column) for column, band in zip(BAND_COLUMNS, BANDS)}
    total = _cell(row, "D")
    if sum(counts.values()) != total:
        raise ValueError(f"표본 표의 연령대 합계가 합계 열과 다릅니다: {row.get('_row')}행")
    return total, counts


def _sheet_province(rows: list[dict], sheet: str) -> str:
    title = next((row["A"] for row in rows if str(row.get("A", "")).startswith("[표본]")), "")
    match = re.fullmatch(r"\[표본\]\[(.+)\]", title)
    if match is None:
        raise ValueError(f"{sheet}: 표본 시트의 시도 표시를 찾지 못했습니다.")
    header = next((row for row in rows if row.get("A") == "구분"), None)
    expected = {"D": "합계", **BAND_COLUMNS}
    if header is None or any(header.get(col) != label for col, label in expected.items()):
        raise ValueError(f"{sheet}: 표본 시트의 연령대 열 구성이 다릅니다.")
    return match.group(1)


def read_age_table(official_zip: Path, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """구시군별 합계 행을 읽어 연구 지역별 연령대 선거인·투표자 수로 합친다."""
    lookup = crosswalk.loc[crosswalk["dataset"] == "election"]
    lookup = lookup.set_index("source_region_code")["region_code"]
    records: dict[str, dict[str, int]] = {}
    with ZipFile(official_zip) as archive:
        for sheet in AGE_SHEETS:
            rows = _sheet_rows(archive, AGE_MEMBER, sheet)
            province = _sheet_province(rows, sheet)
            sheet_total = None
            summed = {f"{kind}_{band}": 0 for kind in "ev" for band in BANDS}
            for position, row in enumerate(rows):
                if row.get("B") != "합계" or row.get("C") != "선거인수":
                    continue
                next_row = rows[position + 1] if position + 1 < len(rows) else {}
                if next_row.get("C") != "투표자수":
                    raise ValueError(f"{sheet}: 선거인수 다음 행이 투표자수가 아닙니다.")
                _, electors = _row_counts(row)
                _, voters = _row_counts(next_row)
                if any(voters[band] > electors[band] for band in BANDS):
                    raise ValueError(f"{sheet}: 투표자수가 선거인수보다 큰 연령대가 있습니다.")
                values = {f"e_{band}": electors[band] for band in BANDS}
                values.update({f"v_{band}": voters[band] for band in BANDS})
                unit = str(row.get("A", "")).strip()
                if unit == "전체":
                    if sheet_total is not None:
                        raise ValueError(f"{sheet}: 전체 행이 중복됩니다.")
                    sheet_total = values
                    continue
                key = f"{province}|{unit}"
                if key in records:
                    raise ValueError(f"표본 표의 구역이 중복됩니다: {key}")
                records[key] = values
                summed = {name: summed[name] + values[name] for name in summed}
            if sheet_total is None or sheet_total != summed:
                raise ValueError(f"{sheet}: 전체 행과 구역 합계가 다릅니다.")
    if set(records) != set(lookup.index):
        unknown = sorted(set(records) ^ set(lookup.index))[:10]
        raise ValueError(f"표본 표와 지역 대응표의 구역이 다릅니다: {unknown}")
    table = pd.DataFrame.from_dict(records, orient="index")
    table["region_code"] = lookup.reindex(table.index).to_numpy()
    return table.groupby("region_code").sum()


def population_bands(population: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """주민등록 연령별 인구를 공식 표와 같은 연령대로 묶는다. 18세 미만은 제외한다."""
    lookup = crosswalk.loc[crosswalk["dataset"] == "population"]
    merged = population.merge(
        lookup[["source_region_code", "region_code"]],
        on="source_region_code",
        how="left",
        validate="many_to_one",
    )
    if merged["region_code"].isna().any():
        raise ValueError("인구 자료에 대응되지 않은 지역이 있습니다.")
    adults = merged.loc[merged["age"] >= 18].copy()
    adults["band"] = pd.cut(
        adults["age"], bins=list(AGE_EDGES), labels=list(BANDS), right=False
    ).astype(str)
    table = adults.pivot_table(
        index="region_code", columns="band", values="population", aggfunc="sum"
    ).reindex(columns=list(BANDS))
    if table.isna().any().any() or (table.sum(axis=1) <= 0).any():
        raise ValueError("연령대별 인구에 비어 있는 구간이 있습니다.")
    return table


def national_rates(age_table: pd.DataFrame) -> pd.Series:
    """공식 전국 표와 같은 합계 기준 연령대 투표율(0~1)."""
    return pd.Series(
        {band: age_table[f"v_{band}"].sum() / age_table[f"e_{band}"].sum() for band in BANDS}
    )


def population_weighted_rates(age_table: pd.DataFrame, bands: pd.DataFrame) -> pd.Series:
    """지역별 표본 추출률 차이를 줄이도록 지역 인구로 가중한 연령대 투표율(감도 분석)."""
    aligned = bands.reindex(age_table.index)
    rates = {}
    for band in BANDS:
        regional = age_table[f"v_{band}"] / age_table[f"e_{band}"]
        rates[band] = float((regional * aligned[band]).sum() / aligned[band].sum())
    return pd.Series(rates)


def composition_expected(shares: pd.DataFrame, rates: pd.Series) -> pd.Series:
    """연령 비중에 전국 연령대 투표율을 곱한 기대 투표율(%)."""
    return 100 * shares[list(BANDS)].mul(rates[list(BANDS)]).sum(axis=1)


def build_region_frame(
    data: pd.DataFrame, age_table: pd.DataFrame, bands: pd.DataFrame
) -> pd.DataFrame:
    """지역별 기대 투표율, 같은 나이대 차이, 보조 표본 지표를 만든다."""
    frame = data.set_index("region_code", drop=False)
    if set(frame.index) != set(age_table.index) or set(frame.index) != set(bands.index):
        raise ValueError("분석 데이터와 연령대 자료의 지역이 다릅니다.")
    age = age_table.reindex(frame.index)
    electors = age[[f"e_{band}" for band in BANDS]]
    voters = age[[f"v_{band}" for band in BANDS]]
    if (electors <= 0).any().any():
        raise ValueError("표본 선거인이 0인 지역·연령대가 있습니다.")
    shares = bands.reindex(frame.index)
    shares = shares.div(shares.sum(axis=1), axis=0)
    rates = national_rates(age_table)

    out = frame.copy()
    out["composition_expected"] = composition_expected(shares, rates)
    out["within_age_difference"] = out["turnout"] - out["composition_expected"]
    out["sample_electors"] = electors.sum(axis=1)
    out["sample_voters"] = voters.sum(axis=1)
    out["sample_turnout"] = 100 * out["sample_voters"] / out["sample_electors"]
    out["sample_fraction"] = out["sample_electors"] / out["electors"]
    out["sample_electors_80plus"] = age["e_80+"]
    out["sample_electors_70s"] = age["e_70-79"]
    rate_80 = age["v_80+"] / age["e_80+"]
    rate_70 = age["v_70-79"] / age["e_70-79"]
    out["rate_80plus"] = 100 * rate_80
    out["rate_70s"] = 100 * rate_70
    out["gap_80plus_minus_70s"] = out["rate_80plus"] - out["rate_70s"]
    out["gap_se_srs"] = 100 * np.sqrt(
        rate_80 * (1 - rate_80) / age["e_80+"] + rate_70 * (1 - rate_70) / age["e_70-79"]
    )
    national_share = pd.Series(
        {band: age_table[f"e_{band}"].sum() for band in BANDS}, dtype=float
    )
    national_share = national_share / national_share.sum()
    regional_rates = pd.DataFrame(
        {band: age[f"v_{band}"] / age[f"e_{band}"] for band in BANDS}
    )
    out["direct_standardized"] = 100 * regional_rates.mul(national_share).sum(axis=1)
    out["sample_share_expected"] = 100 * (
        electors.div(electors.sum(axis=1), axis=0).rename(
            columns=lambda name: name.removeprefix("e_")
        )
    ).mul(rates).sum(axis=1)
    return out.reset_index(drop=True)


def _fit(formula: str, sample: pd.DataFrame, weights: pd.Series | None = None):
    """기존 모형과 같은 HC3 정규근사. 식별 불가·상수 종속변수는 성공으로 보고하지 않는다."""
    if weights is None:
        model = smf.ols(formula, data=sample, missing="raise")
    else:
        model = smf.wls(formula, data=sample, weights=weights, missing="raise")
    x = np.asarray(model.wexog, dtype=float)
    if np.ptp(model.endog) <= 1e-12:
        raise ValueError(f"종속변수가 상수입니다: {formula}")
    if x.shape[0] <= x.shape[1] or np.linalg.matrix_rank(x) != x.shape[1]:
        raise ValueError(f"설계행렬이 식별되지 않습니다: {formula}")
    q, _ = np.linalg.qr(x, mode="reduced")
    if (1 - np.square(q).sum(axis=1) <= 1e-12).any():
        raise ValueError(f"leverage가 1에 가까워 HC3를 정의할 수 없습니다: {formula}")
    fitted = model.fit(cov_type="HC3", use_t=False)
    if not np.isfinite(np.concatenate([fitted.params, fitted.bse])).all():
        raise ValueError(f"유한하지 않은 추정 결과입니다: {formula}")
    return fitted


def common_sample(frame: pd.DataFrame) -> pd.DataFrame:
    """기본 M4와 같은 지역 집합: 특수지역을 뺀 완전 사례."""
    needed = [
        "turnout", "aging_rate", "oldest_share", "fiscal_independence",
        "net_migration_rate", "log_population", "region_type", "province", "electors",
    ]
    return frame.loc[frame["region_type"].ne("특수지역") & frame[needed].notna().all(axis=1)].copy()


def fit_components(frame: pd.DataFrame) -> pd.DataFrame:
    """실제·구성·같은 나이대 차이를 같은 식으로 회귀하고 계수의 합을 검사한다."""
    sample = common_sample(frame)
    rows = []
    for name, base, weighted in SPECIFICATIONS:
        right_side = FORMULAS[base].split("~", 1)[1].strip()
        weights = sample["electors"] if weighted else None
        fits = {
            component: _fit(f"{column} ~ {right_side}", sample, weights)
            for component, column in COMPONENTS.items()
        }
        difference = (
            fits["actual"].params - fits["composition"].params - fits["within_age"].params
        )
        if (difference.abs() > TOLERANCE).any():
            raise ValueError(f"{name}: 실제 계수와 분해 계수의 합이 다릅니다.")
        for component, fitted in fits.items():
            interval = fitted.conf_int(alpha=0.05)
            for term in fitted.params.index:
                rows.append(
                    {
                        "model": name,
                        "component": component,
                        "term": term,
                        "n": int(fitted.nobs),
                        "estimate": float(fitted.params[term]),
                        "std_error_hc3": float(fitted.bse[term]),
                        "p_value": float(fitted.pvalues[term]),
                        "ci_low": float(interval.loc[term, 0]),
                        "ci_high": float(interval.loc[term, 1]),
                        "r_squared": float(fitted.rsquared),
                    }
                )
    return pd.DataFrame(rows)


def sensitivity_table(
    frame: pd.DataFrame, age_table: pd.DataFrame, bands: pd.DataFrame
) -> pd.DataFrame:
    """M4 분해가 연령대 투표율·연령 비중의 기준에 민감한지 비교한다."""
    aligned = frame.set_index("region_code", drop=False)
    shares = bands.reindex(aligned.index)
    shares = shares.div(shares.sum(axis=1), axis=0)
    variants = {
        "main_pooled_rates_population_shares": aligned["composition_expected"],
        "population_weighted_rates": composition_expected(
            shares, population_weighted_rates(age_table, bands)
        ),
        "sample_elector_shares": aligned["sample_share_expected"],
    }
    right_side = FORMULAS["M4"].split("~", 1)[1].strip()
    rows = []
    for variant, expected in variants.items():
        sample = common_sample(aligned.assign(expected_variant=expected))
        sample["difference_variant"] = sample["turnout"] - sample["expected_variant"]
        for component, column in [
            ("composition", "expected_variant"),
            ("within_age", "difference_variant"),
        ]:
            fitted = _fit(f"{column} ~ {right_side}", sample)
            interval = fitted.conf_int(alpha=0.05)
            for term in ["aging_rate", "oldest_share"]:
                rows.append(
                    {
                        "variant": variant,
                        "component": component,
                        "term": term,
                        "estimate": float(fitted.params[term]),
                        "ci_low": float(interval.loc[term, 0]),
                        "ci_high": float(interval.loc[term, 1]),
                    }
                )
    return pd.DataFrame(rows)


def _cook_exclusions(fitted, n: int) -> np.ndarray:
    return fitted.get_influence().cooks_distance[0] <= 4 / n


def sign_checks(frame: pd.DataFrame) -> pd.DataFrame:
    """X2 부호가 M3와 M4에서 달라지는 이유의 경쟁 설명을 같은 표에서 비교한다."""
    sample = common_sample(frame)
    controls = "fiscal_independence + net_migration_rate + log_population"
    base = f"turnout ~ aging_rate + oldest_share + {controls}"
    honam = sample["province"].isin(HONAM)
    cook_keep = _cook_exclusions(smf.ols(base, data=sample, missing="raise").fit(), len(sample))
    all_regions = frame.loc[frame[["fiscal_independence", "net_migration_rate"]].notna().all(axis=1)]
    checks = [
        ("M3_common", "기준", base, sample),
        ("without_X1", "X1과의 공선성", f"turnout ~ oldest_share + {controls}", sample),
        ("include_special_regions", "세종·제주 제외", base, all_regions),
        ("exclude_m3_cook", "영향점", base, sample.loc[cook_keep]),
        ("add_region_type", "지역유형", f"{base} + C(region_type)", sample),
        ("add_honam_dummy", "호남 3개 시도", f"{base} + honam", sample.assign(honam=honam.astype(int))),
        ("exclude_honam", "호남 3개 시도", base, sample.loc[~honam]),
        ("add_province", "시도 효과", f"{base} + C(province)", sample),
        ("M4", "지역유형+시도", f"{base} + C(region_type) + C(province)", sample),
    ]
    rows = []
    for label, explanation, formula, data in checks:
        row = {"check": label, "explanation": explanation, "n": len(data), "formula": formula}
        try:
            fitted = _fit(formula, data)
        except ValueError as error:
            row.update({"status": "NOT_APPLICABLE", "note": str(error)})
            rows.append(row)
            continue
        interval = fitted.conf_int(alpha=0.05)
        row.update({"status": "PASS", "note": "", "r_squared": float(fitted.rsquared)})
        for short, term in [("x1", "aging_rate"), ("x2", "oldest_share")]:
            if term in fitted.params.index:
                row[f"{short}_estimate"] = float(fitted.params[term])
                row[f"{short}_ci_low"] = float(interval.loc[term, 0])
                row[f"{short}_ci_high"] = float(interval.loc[term, 1])
        rows.append(row)
    return pd.DataFrame(rows)


def province_table(frame: pd.DataFrame) -> pd.DataFrame:
    """시도별 실제·기대·조정 투표율. 조정값은 전수 자료만 쓴다."""
    national_expected = np.average(frame["composition_expected"], weights=frame["electors"])
    rows = []
    for province, group in frame.groupby("province"):
        actual = 100 * group["voters"].sum() / group["electors"].sum()
        expected = np.average(group["composition_expected"], weights=group["electors"])
        rows.append(
            {
                "province": province,
                "regions": len(group),
                "actual_turnout": actual,
                "composition_expected": expected,
                "age_adjusted_turnout": actual - expected + national_expected,
                "direct_standardized": np.average(
                    group["direct_standardized"], weights=group["electors"]
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("age_adjusted_turnout", ascending=False)


def gap_summary(frame: pd.DataFrame) -> dict:
    """80세 이상과 70대의 격차 요약. 설계효과 값은 점검용 가정이다."""
    gap = frame["gap_80plus_minus_70s"]
    excludes_zero = {
        str(effect): int((gap + Z_95 * frame["gap_se_srs"] * np.sqrt(effect) < 0).sum())
        for effect in DESIGN_EFFECTS
    }
    return {
        "regions": int(len(gap)),
        "regions_80plus_below_70s": int((gap < 0).sum()),
        "median": float(gap.median()),
        "min": float(gap.min()),
        "max": float(gap.max()),
        "regions_upper_bound_below_zero_by_design_effect": excludes_zero,
    }


def variance_summary(frame: pd.DataFrame) -> dict:
    """지역 간 차이의 크기. 시도 설명력은 기본 M4와 같은 지역에서 계산한다."""
    sample = common_sample(frame)
    within = smf.ols("within_age_difference ~ C(province)", data=sample).fit()
    return {
        "regions": int(len(frame)),
        "sd_actual": float(frame["turnout"].std()),
        "sd_composition": float(frame["composition_expected"].std()),
        "sd_within_age": float(frame["within_age_difference"].std()),
        "sd_direct_standardized": float(frame["direct_standardized"].std()),
        "corr_composition_actual": float(
            np.corrcoef(frame["composition_expected"], frame["turnout"])[0, 1]
        ),
        "province_r_squared_within_age_226": float(within.rsquared),
        "sample_turnout_mean_abs_difference": float(
            (frame["turnout"] - frame["sample_turnout"]).abs().mean()
        ),
        "sample_turnout_max_abs_difference": float(
            (frame["turnout"] - frame["sample_turnout"]).abs().max()
        ),
        "sample_fraction_min": float(frame["sample_fraction"].min()),
        "sample_fraction_median": float(frame["sample_fraction"].median()),
        "sample_fraction_max": float(frame["sample_fraction"].max()),
        "sample_electors_80plus_min": int(frame["sample_electors_80plus"].min()),
    }


def _plot_components(coefficients: pd.DataFrame, path: Path) -> None:
    selected = coefficients.loc[coefficients["model"] == "M4"].set_index(["component", "term"])
    rows = [
        ("actual", "Actual turnout"),
        ("composition", "Age composition"),
        ("within_age", "Same-age regional\ndifference"),
    ]
    panels = [("aging_rate", "Aging rate (X1)"), ("oldest_share", "Share aged 80+ (X2)")]
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.6), sharex=True, sharey=True, layout="constrained")
    positions = {component: len(rows) - 1 - i for i, (component, _) in enumerate(rows)}
    for axis, (term, title) in zip(axes, panels):
        axis.axvline(0, color=COLOR_REFERENCE, linewidth=1, linestyle="--")
        for component, _ in rows:
            row = selected.loc[(component, term)]
            y = positions[component]
            if component != "composition":
                axis.plot([row["ci_low"], row["ci_high"]], [y, y], color=COLOR_MAIN, linewidth=2)
            axis.plot(row["estimate"], y, "o", color=COLOR_MAIN, markersize=8)
            axis.annotate(
                f"{row['estimate']:+.3f}",
                (row["estimate"], y),
                xytext=(0, 9),
                textcoords="offset points",
                ha="center",
                fontsize=9,
            )
        axis.set_title(title, fontsize=11)
        axis.set_xlabel("Turnout difference (pp per 1 pp)")
        axis.set_xticks(np.arange(-0.2, 0.21, 0.1))
        axis.set_ylim(-0.6, len(rows) - 0.4)
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="x", color="#e6e5e0", linewidth=0.8)
        axis.set_axisbelow(True)
    axes[0].set_yticks([positions[c] for c, _ in rows], [label for _, label in rows])
    fig.suptitle("M4 coefficients split into two parts (226 regions)", fontsize=12)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_expected_actual(frame: pd.DataFrame, path: Path) -> None:
    honam = frame["province"].isin(HONAM)
    limits = (72.5, 87.5)
    fig, ax = plt.subplots(figsize=(6.4, 6.0), layout="constrained")
    ax.plot(limits, limits, color=COLOR_REFERENCE, linewidth=1, linestyle="--", label="Expected = actual")
    for mask, color, label in [
        (~honam, COLOR_MAIN, "Other regions"),
        (honam, COLOR_ACCENT, "Gwangju, Jeonnam, Jeonbuk"),
    ]:
        ax.scatter(
            frame.loc[mask, "composition_expected"],
            frame.loc[mask, "turnout"],
            s=42,
            color=color,
            alpha=0.75,
            edgecolors="white",
            linewidths=0.8,
            label=label,
        )
    ax.set(
        xlim=limits,
        ylim=limits,
        aspect="equal",
        xlabel="Turnout expected from age composition alone (%)",
        ylabel="Actual turnout (%)",
        title=f"Age composition explains little of the regional spread ({len(frame)} regions)",
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(color="#e6e5e0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=False)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def run_decomposition(
    data_path: Path,
    quality_path: Path,
    population_path: Path,
    crosswalk_path: Path,
    official_zip: Path,
    output_dir: Path,
) -> dict:
    """인증서와 입력 연결을 먼저 확인한 뒤 표·그림·manifest를 만든다."""
    quality = verify_dataset_certificate(data_path, quality_path)
    for path in [population_path, crosswalk_path, official_zip]:
        if str(Path(path).resolve()) not in quality["verified_files"]:
            raise ValueError(f"인증서에 연결되지 않은 입력입니다: {path}")
    data = pd.read_csv(data_path, dtype={"region_code": str})
    crosswalk = pd.read_csv(crosswalk_path, dtype=str, keep_default_na=False)
    population = pd.read_csv(population_path, dtype={"source_region_code": str})
    age_table = read_age_table(official_zip, crosswalk)
    bands = population_bands(population, crosswalk)
    frame = build_region_frame(data, age_table, bands)
    coefficients = fit_components(frame)
    sensitivity = sensitivity_table(frame, age_table, bands)
    checks = sign_checks(frame)
    provinces = province_table(frame)
    rates = pd.DataFrame(
        {
            "band": list(BANDS),
            "sample_electors": [int(age_table[f"e_{band}"].sum()) for band in BANDS],
            "sample_voters": [int(age_table[f"v_{band}"].sum()) for band in BANDS],
            "pooled_rate_pct": (100 * national_rates(age_table)).to_numpy(),
            "population_weighted_rate_pct": (
                100 * population_weighted_rates(age_table, bands)
            ).to_numpy(),
        }
    )
    tables = output_dir / "tables"
    figures = output_dir / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    region_columns = [
        "region_code", "region_name", "province", "region_type", "electors", "turnout",
        "aging_rate", "oldest_share", "composition_expected", "within_age_difference",
        "sample_electors", "sample_voters", "sample_turnout", "sample_fraction",
        "sample_electors_80plus", "sample_electors_70s", "rate_80plus", "rate_70s",
        "gap_80plus_minus_70s", "gap_se_srs", "direct_standardized", "sample_share_expected",
    ]
    outputs = {
        tables / "decomposition_regions.csv": frame[region_columns],
        tables / "decomposition_national_rates.csv": rates,
        tables / "decomposition_coefficients.csv": coefficients,
        tables / "decomposition_sensitivity.csv": sensitivity,
        tables / "decomposition_sign_checks.csv": checks,
        tables / "decomposition_provinces.csv": provinces,
    }
    for path, table in outputs.items():
        table.to_csv(path, index=False)
    component_figure = figures / "decomposition_m4.png"
    scatter_figure = figures / "decomposition_expected_actual.png"
    _plot_components(coefficients, component_figure)
    _plot_expected_actual(frame, scatter_figure)
    manifest = {
        "gate": "G-POST-02",
        "decision": "ADR-014",
        "status": "decomposition_outputs_generated",
        "exploratory_not_preregistered": True,
        "hypothesis_verdicts_changed": False,
        "dataset_sha256": quality["dataset_sha256"],
        "quality_sha256": _sha(quality_path),
        "code_sha256": _sha(Path(__file__)),
        "gaps": gap_summary(frame),
        "variance": variance_summary(frame),
        "artifacts": {
            str(path.relative_to(output_dir)): _sha(path)
            for path in [*outputs, component_figure, scatter_figure]
        },
    }
    (output_dir / "decomposition_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="나이 구성과 같은 나이대 차이의 분해 (탐색 분석)")
    parser.add_argument("--data", type=Path, default=Path("outputs/current/analysis_dataset.csv"))
    parser.add_argument(
        "--quality-report", type=Path, default=Path("outputs/current/data_quality.json")
    )
    parser.add_argument("--population", type=Path, default=Path("data/interim/population.csv"))
    parser.add_argument(
        "--crosswalk", type=Path, default=Path("data/reference/region_crosswalk.csv")
    )
    parser.add_argument(
        "--official-election-zip",
        type=Path,
        default=Path("data/raw/제21대 대통령선거 투표율 분석.zip"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/current"))
    args = parser.parse_args()
    manifest = run_decomposition(
        args.data,
        args.quality_report,
        args.population,
        args.crosswalk,
        args.official_election_zip,
        args.output_dir,
    )
    print(f"분해 분석 완료: {manifest['variance']['regions']}개 지역. 사전 계획 외 탐색 결과임.")


if __name__ == "__main__":
    main()
