"""검증된 지역 데이터의 독립 탐색분석. 회귀모형은 실행하지 않는다."""

from __future__ import annotations

import argparse
import hashlib
import json
from itertools import combinations
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from political_analysis.pipeline import verify_dataset_certificate

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CORE_COLUMNS = ["turnout", "aging_rate", "oldest_share"]


def exploration_tables(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """결측·상수의 상태와 쌍별 유효 n을 보존한다. 인공 단위 테스트에도 사용한다."""
    if data.empty:
        raise ValueError("탐색 데이터가 비어 있습니다.")
    missing = set(CORE_COLUMNS) - set(data.columns)
    if missing:
        raise ValueError(f"탐색 필수 컬럼 누락: {sorted(missing)}")
    numeric = data.drop(columns="region_code", errors="ignore").select_dtypes(include="number")
    if not set(CORE_COLUMNS).issubset(numeric.columns):
        raise ValueError("탐색 핵심 변수는 숫자형이어야 합니다.")
    if np.isinf(numeric.to_numpy(dtype=float, na_value=np.nan)).any():
        raise ValueError("탐색 변수에 무한대가 있습니다.")
    descriptive = numeric.describe().transpose()
    descriptive["missing"] = numeric.isna().sum()
    correlations = numeric[CORE_COLUMNS].corr(method="pearson")
    pairs = []
    for x, y in combinations(CORE_COLUMNS, 2):
        valid = numeric[[x, y]].dropna()
        status = "ok"
        if len(valid) < 2:
            status = "insufficient_pairs"
        elif valid[x].nunique() < 2 or valid[y].nunique() < 2:
            status = "constant_variable"
        pairs.append(
            {
                "x": x,
                "y": y,
                "n": len(valid),
                "pearson_r": float(correlations.loc[x, y]),
                "status": status,
            }
        )
    return descriptive, correlations, pd.DataFrame(pairs)


def run_exploration(data_path: Path, output_dir: Path, quality_path: Path) -> dict:
    """파일 기반 실행은 인증서와 모든 연결 해시 확인을 필수로 한다."""
    quality = verify_dataset_certificate(data_path, quality_path)
    frame = pd.read_csv(data_path, dtype={"region_code": "string"})
    descriptive, correlations, pairs = exploration_tables(frame)
    tables = output_dir / "tables"
    figures = output_dir / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    descriptive.to_csv(tables / "descriptive_statistics.csv")
    correlations.to_csv(tables / "correlations.csv")
    pairs.to_csv(tables / "correlation_pairs.csv", index=False)

    scatter = frame[["aging_rate", "turnout"]].dropna()
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    if len(scatter):
        ax.scatter(scatter["aging_rate"], scatter["turnout"], alpha=0.65, s=28)
    else:
        ax.text(
            0.5, 0.5, "No complete observations", ha="center", va="center", transform=ax.transAxes
        )
    ax.set_xlabel("65+ / 18+ population (%)")
    ax.set_ylabel("Turnout (%)")
    ax.set_title("2025 presidential election: aging and turnout")
    fig.tight_layout()
    figure = figures / "scatter_aging_turnout.png"
    fig.savefig(figure, dpi=180)
    plt.close(fig)

    artifacts = [
        tables / "descriptive_statistics.csv",
        tables / "correlations.csv",
        tables / "correlation_pairs.csv",
        figure,
    ]
    manifest = {
        "status": "exploration_generated",
        "dataset_sha256": quality["dataset_sha256"],
        "quality_sha256": hashlib.sha256(quality_path.read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "observations": len(frame),
        "scatter_complete_pairs": len(scatter),
        "scatter_status": "plotted" if len(scatter) else "no_complete_pairs",
        "pair_status_counts": {str(k): int(v) for k, v in pairs.status.value_counts().items()},
        "regression_executed_by_exploration": False,
        "artifacts": {
            str(p.relative_to(output_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in artifacts
        },
        "note": "지역 수준 탐색 통계. 인과효과·개인 투표행동·가설 유의성 판단이 아님. "
        "공식 지역별 교부수/개표 범위 조정은 독립 재검증과 구별함.",
    }
    (output_dir / "exploration_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="인증된 지역 데이터의 독립 탐색분석")
    parser.add_argument("--data", type=Path, default=Path("data/processed/analysis_dataset.csv"))
    parser.add_argument("--quality-report", type=Path, default=Path("outputs/data_quality.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    result = run_exploration(args.data, args.output_dir, args.quality_report)
    print(f"탐색 산출물 생성: {result['observations']}개 지역, 회귀 실행 없음.")


if __name__ == "__main__":
    main()
