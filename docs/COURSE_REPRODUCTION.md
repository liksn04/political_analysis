# 과제 개정본과 재현 자료

원고는 [수업 최종보고서 개정본](COURSE_REPORT_REVISED.md)이다. 아래 자료는 연구 폴더에서 원고와 함께 열어 볼 수 있다.

| 자료 | 위치 |
| --- | --- |
| 시군구 228개 분석 데이터 | `outputs/course-revision/analysis_dataset.csv` |
| 각 지역의 65·75·80·85세 이상 집계 | `outputs/course-revision/tables/age_threshold_counts.csv` |
| 75·80·85세 민감도 결과 | `outputs/course-revision/tables/age_threshold_sensitivity.csv` |
| 기본 회귀 원표 | `outputs/course-revision/tables/model_coefficients.csv` · `outputs/course-revision/tables/model_samples.csv` |
| 사후 탐색 분석 원표 | `outputs/course-revision/tables/decomposition_regions.csv` · `outputs/course-revision/tables/decomposition_coefficients.csv` |
| 분석 코드 | [기본 회귀](../src/political_analysis/models.py) · [연령 기준 민감도](../scripts/age_threshold_sensitivity.py) · [연령구성 분해](../src/political_analysis/decomposition.py) |

## 재실행

저장소 루트에서 프로젝트 가상환경을 활성화한다. 새 환경에서는 먼저 `python -m pip install -e ".[dev]"`로 코드와 의존성을 설치한다. 새 체크아웃에서는 [README의 재실행 절차](../README.md#연구-자료와-재실행)에 따라 지역 검증에 필요한 행정안전부 PDF를 받는다. 공식 원자료와 조회 조건은 [출처 대장](SOURCES.md)에서 확인한다. `make build`는 저장소의 `data/raw/`, `data/interim/`, `data/reference/` 및 기존 스테이징 검증 기록을 사용한다. 인증서에는 실제 경로가 들어가므로 실행할 환경에서 다시 생성한다.

```sh
replay_dir=$(mktemp -d "$PWD/outputs/course-replay.XXXXXXXX")
make build analyze decompose RUN_DIR="$replay_dir"
python scripts/age_threshold_sensitivity.py --run-dir "$replay_dir"
cmp "$replay_dir/tables/model_coefficients.csv" outputs/course-revision/tables/model_coefficients.csv
cmp "$replay_dir/tables/age_threshold_sensitivity.csv" outputs/course-revision/tables/age_threshold_sensitivity.csv
```

2026-11-22 같은 환경에서 별도 경로로 재실행한 결과, 분석 데이터와 모델 계수·표본, 민감도 분석과 연령별 인원, 분해 계수와 전국 연령별 투표율 등 CSV 7개가 바이트 단위로 일치했다. 기본 회귀 계수와 표본은 기존 보관본과도 일치했다.

수업 제출 시에는 위 표에서 필요한 파일을 선택한다. 기관 원자료는 출처 대장에 기록된 공식 경로와 이용조건을 따른다.
