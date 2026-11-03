# 지역의 고령화 수준과 선거 투표율의 관계

**2025년 제21대 대통령선거에서 고령층 내부의 연령구성을 고려한 시군구별 실증분석**

이 저장소는 2025년 6월 3일 실시된 제21대 대통령선거의 전국 시군구 수준에서 지역 고령화와 투표율의 **통계적 연관성**을 검증하기 위한 재현 가능한 Python 연구 프로젝트입니다. 아직 공식 원자료를 수집하거나 연구 가설을 실증 검증한 것은 아닙니다. 검증 전 결과를 생성하거나 실제 통계처럼 서술하지 않습니다.

## 연구질문과 가설

- **RQ:** 지역의 고령화 수준은 대통령선거 투표율과 어떤 관계를 가지며, 지역 조건이 유사할 때 65세 이상 인구 중 80세 이상 비중은 어떤 추가 관계를 보이는가?
- **H1:** 성인인구 중 65세 이상 비중이 높은 지역일수록 전체 투표율이 높을 것이다.
- **H2:** 고령화 수준과 다른 조건이 같을 때, 고령층 내 80세 이상 비중이 높은 지역일수록 전체 투표율이 낮을 것이다.

| 지표 | 정의 |
|---|---|
| 투표율 Y | 투표자 수 / 선거인 수 × 100 |
| 고령화 수준 X1 | 65세 이상 주민등록인구 / 18세 이상 주민등록인구 × 100 |
| 초고령 비중 X2 | 80세 이상 주민등록인구 / 65세 이상 주민등록인구 × 100 |

X1은 일반적으로 말하는 **전체 인구 중 65세 이상 비중**이 아니라 **18세 이상 인구 대비 비율**임에 유의합니다. 분석 단위는 개인이 아닌 **지역**이며, 단면 회귀계수는 인과효과가 아닙니다.

## 현재 상태

- [x] 연구질문·가설·조작적 정의 및 기본 분석환경 수립
- [x] 표준 입력파일 형식, 지역코드 대응표, 데이터 품질 검사 및 분석모형 코드 준비
- [ ] 공식 원자료 확보 및 이용조건 확인
- [ ] 2025년 행정구역 코드 대응표 **실제 값** 입력 및 검수
- [ ] 표준 입력파일 생성, 공식 합계 대조, 결합 검증
- [ ] 기술통계·회귀분석·강건성 분석 및 보고서 작성

> **중요:** 이 저장소에 포함된 `data/templates/`는 **헤더만 있는 양식**입니다. 원자료, 완성된 지역 대응표, 분석결과는 포함되지 않았습니다. 코드 작성 완료와 데이터 검증 완료는 다릅니다.

## 개발환경

Python **3.11 이상**을 사용합니다.

```bash
git clone https://github.com/liksn04/political_analysis.git
cd political_analysis
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
make test                       # 코드와 인공 테스트 데이터로만 검증
```

## 데이터 수집 및 분석 흐름

1. [공식 자료 출처](docs/SOURCES.md)의 다섯 자료를 다운로드하여 `data/raw/`에 원형으로 보관합니다.
2. 공식 파일의 열 이름·집계 단위·기준일을 확인한 다음 `data/templates/`의 형식으로 변환하여 `data/interim/`에 저장합니다. **원본 형식을 임의로 가정하는 자동 수집기는 포함하지 않습니다.**
3. `data/templates/region_crosswalk.csv`를 참고하여 `data/reference/region_crosswalk.csv`를 작성합니다. 모든 원본 지역코드가 검증된 2025년 분석단위에 대응해야 합니다.
4. 다음 명령으로 자료를 결합하고 검증합니다.

```bash
make build
make analyze
```

`make build`는 아래 파일이 존재해야 동작합니다.

- `data/interim/election.csv`: **상호 중복되지 않는** 지역별 선거인수·투표자수
- `data/interim/population.csv`: 2025년 5월 기준, 지역별·연령별 주민등록인구
- `data/interim/fiscal.csv`: 2025년 당초예산 기준 재정자립도
- `data/interim/migration.csv`: 2024년 순이동자수와 연앙인구
- `data/reference/region_crosswalk.csv`: 원본 지역코드 → 분석 지역코드

`make build` 결과: `data/processed/analysis_dataset.csv`, `outputs/data_quality.json`. `make analyze` 결과: `outputs/tables/model_coefficients.csv`, `model_summary.csv`, `outputs/figures/scatter_aging_turnout.png` 및 `outputs/model_notes.txt`.

입력/결과 CSV는 개인정보가 없더라도 우선 Git 추적에서 제외합니다. 자료의 라이선스와 재배포 조건 확인 후 공개 여부를 별도 결정합니다.

## 프로젝트 문서

- [연구설계와 분석 프로토콜](docs/PROTOCOL.md)
- [자료 출처와 수집 요건](docs/SOURCES.md)
- [변수·파일 코드북](docs/CODEBOOK.md)
- [8주 연구 로드맵](docs/ROADMAP.md)
- [방법론적 결정과 보류사항](docs/DECISIONS.md)
- [연구 진행 기록](docs/RESEARCH_LOG.md)

## 연구 원칙

공식 통계의 **집계 계층 중복**, 행정구역 불일치, 2025년 조기선거의 특수성, **생태학적 오류**를 명시적으로 관리합니다. 유의미한 관계가 나타나지 않더라도 결과를 삭제하거나 가설을 변경하지 않습니다. 단, 실제 분석 결과 및 계수는 원자료 수집·검증 후에만 보고합니다.
