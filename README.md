# 지역의 고령화 수준과 선거 투표율의 관계

**2025년 제21대 대통령선거에서 고령층 내부의 연령구성을 고려한 시군구별 실증분석**

이 저장소는 2025년 6월 3일 실시된 제21대 대통령선거의 전국 시군구 수준에서 지역 고령화와 투표율의 **통계적 연관성**을 검증하기 위한 재현 가능한 Python 연구 프로젝트입니다. 공식 원자료의 범위·지역 대응·합계를 검수하고 사전 OLS HC3 모형의 실제 추정과 가설 평가를 마쳤습니다. 가중치·공통표본·특수지역 감도분석, 공선성·영향점 진단, 탐색적 상호작용 분석을 마쳤습니다.

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
- [x] 공식 원자료 확보 및 이용조건 확인 (공식 개방 목록·KOSIS 이용지침 확인)
- [x] 2025년 분석 지역 명부·코드 대응표 실제 값 입력 및 계층 검수 (G-M2-01)
- [x] 표준 입력파일 생성, 공식 합계 대조, 결합 검증 (전국·시도 직접 대조 / 지역별 기준 조정 구별)
- [x] 기술통계·상관·산점도 및 이상치 후보 원본 검수 (M3, 삭제 0지역)
- [x] 사전 OLS HC3 추정·모형별 가설 평가 (M4)
- [x] 강건성 점검 및 탐색적 상호작용 (M5)
- [x] 연구 보고서 초고 (G-M6-01)
- [x] 인용·주장·보고 완전성 검수 (G-M6-02)
- [x] 별도 환경 재실행 (G-M7-01, 별도 AI 검증자 재실행 통과·동일 호스트)
- [x] 최종 보고서·공유범위·인계 확정 (G-M7-02)
- [x] 사전 계획 외 탐색 분석: 나이 구성과 같은 나이대 차이의 분해 (G-POST-02)

제출한 연구계획서와 발표 자료, 공식 원자료, 지역 대응표, 정제 데이터, 분석 결과 및 재현 기록을 이 저장소에 보관합니다. `data/templates/`는 헤더가 있는 입력 양식입니다.

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
2. 공식 파일의 열 이름·집계 단위·기준일을 확인한 다음 `data/templates/`의 형식으로 변환하여 `data/interim/`에 저장합니다. **원본 형식을 임의로 가정하는 자동 수집기는 포함하지 않습니다.** 확인한 원본의 변환 명령은 [코드북](docs/CODEBOOK.md)의 ‘원본 변환 실행’ 절에 있습니다.
3. `data/templates/region_crosswalk.csv`를 참고하여 `data/reference/region_crosswalk.csv`를 작성합니다. 모든 원본 지역코드가 검증된 2025년 분석단위에 대응해야 합니다.
4. 다음 명령으로 자료를 결합하고 검증합니다.

```bash
make build
make explore                    # 회귀 없이 인증서 기반 탐색
make analyze                    # 탐색 검수 후 회귀 단계에서 실행
make decompose                  # 사전 계획 외 탐색 분석 (ADR-014)
make audit-decomposition        # 분해 결과를 별개 코드로 재계산
```

`make build`는 아래 파일이 존재해야 동작합니다.

- `data/interim/election.csv`: **상호 중복되지 않는** 지역별 선거인수·투표자수
- `data/interim/population.csv`: 2025년 5월 기준, 지역별·연령별 주민등록인구
- `data/interim/fiscal.csv`: 2025년 당초예산 기준 재정자립도
- `data/interim/migration.csv`: 2024년 순이동자수와 연앙인구
- `data/reference/region_crosswalk.csv`: 원본 지역코드 → 분석 지역코드
- 검증 입력: `data/reference/`의 `expected_regions.csv`·`region_source_inventory.csv`·`midyear_region_crosswalk.csv`, `data/raw/`의 원본, `outputs/`의 `*_staging_checks.*`·`region_mapping_checks.json`

`make` 명령의 결과는 모두 `outputs/current/`에 저장합니다. 분석 데이터는 `analysis_dataset.csv`, 인증서는 `data_quality.json`, 공식 대조표는 `official_reconciliation.csv`이고, 표와 그림은 `tables/`·`figures/`에, 모형 기록은 `model_notes.txt`·`model_manifest.json`에 있습니다. 다른 폴더를 쓰려면 `make build RUN_DIR=경로`처럼 지정합니다.

인증서는 발급 시점의 분석 데이터와 실행 코드 경로에 연결됩니다. 다른 체크아웃으로 이동하거나 검증에 연결된 코드가 바뀌면 해당 경로에서 `make build`로 새 인증서를 발급한 뒤 탐색·분석을 실행합니다.

자료 출처와 조회 조건은 [출처 대장](docs/SOURCES.md)에 기록했습니다. 새로 수집하거나 재실행한 파일은 자료에 맞춰 선택적으로 추가합니다.

## 보관본과 현재 실행

`outputs/data_quality.json`, `outputs/tables/`, `outputs/figures/`, `data/processed/` 등은 보고서와 재현 검증에 연결된 보관본입니다. `make` 명령은 이 파일들을 덮어쓰지 않습니다. 근거는 [ADR-013](docs/DECISIONS.md)에 있습니다.

- 보관 인증서 `outputs/data_quality.json`은 인증서 경로 패치 전의 `pipeline.py` 해시를 담고 있어 현재 코드로는 검증을 통과하지 않습니다. 보관 기록의 상태이며 분석 수치와는 무관합니다.
- `outputs/*_audit.py`는 보관 인증서를 쓰도록 경로가 고정되어 있어 이 폴더에서 실행하면 인증서 검사에서 멈춥니다. 강건성 표와 그림까지 다시 만들려면 [재실행 안내](outputs/reproduction/README.md)의 절차로 별도 체크아웃에서 실행합니다.
- 인자 없이 `python -m political_analysis.pipeline`을 실행하면 기본값인 보관본 경로에 덮어씁니다. 모듈을 직접 실행할 때는 출력 경로를 지정합니다.
- 스테이징 모듈을 기본값으로 실행하면 `data/interim/`과 `outputs/*_staging_checks.*`를 덮어쓰고, 검사 보고서에 별도로 기록한 재계산 증거가 사라집니다. 이 폴더에서는 `--output`·`--report`·`--checks`로 다른 경로를 지정합니다.

## 연구 자료와 재실행

- [제출한 연구계획서](docs/2023010460_%EA%B9%80%EC%A4%80%EB%AA%A8_%EC%97%B0%EA%B5%AC%EA%B3%84%ED%9A%8D%EC%84%9C.docx) · [계획서 초안](docs/PROPOSAL_DRAFT_SKELETON.md)
- [발표 슬라이드](presentation/발표슬라이드.html) · [발표 원고](presentation/발표원고.md)
- [원자료](data/raw/) · [지역 대응표](data/reference/) · [정제 데이터](data/processed/) · [분석 결과](outputs/)
- [개정 보고서](docs/COURSE_REPORT_REVISED.md) · [개정 분석 재실행](docs/COURSE_REPRODUCTION.md) · [기존 재현 검증 기록](outputs/reproduction/README.md)

새 체크아웃에서 분석을 다시 실행하려면 [행정안전부의 2025년 지방자치단체 행정구역 및 인구 현황 PDF](https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000055&nttId=118777)를 받아 `data/raw/mois_2025_regions_20241231.pdf`로 저장합니다. 이 PDF는 지역 자료 검증의 입력입니다. [2024년 국내인구이동 보도자료 통계표 XLS](https://mods.go.kr/board.es?act=view&bid=205&list_no=434904&mid=a10301020400)는 참고용입니다. 두 첨부 원본은 기관 게시물에서 제공하며 [출처 대장](docs/SOURCES.md)에 파일 해시가 있습니다.

`data/raw/제21대 대통령선거 투표율 분석.zip`의 출처는 중앙선거관리위원회(2025)의 「제21대 대통령선거 투표율 분석」입니다. [공공데이터포털 원문](https://www.data.go.kr/data/15156333/fileData.do) · [공공누리 제1유형](https://www.kogl.or.kr/info/licenseType1.do)

## 프로젝트 문서

- [연구설계와 분석 프로토콜](docs/PROTOCOL.md)
- [자료 출처와 수집 요건](docs/SOURCES.md)
- [변수·파일 코드북](docs/CODEBOOK.md)
- [8주 연구 로드맵](docs/ROADMAP.md)
- [방법론적 결정과 보류사항](docs/DECISIONS.md)
- [연구 진행 기록](docs/RESEARCH_LOG.md)
- [보충 보고서: 나이 구성과 같은 나이대 차이의 분해](docs/SUPPLEMENT_DECOMPOSITION.md)

## 연구 원칙

공식 통계의 **집계 계층 중복**, 행정구역 불일치, 2025년 조기선거의 특수성, **생태학적 오류**를 명시적으로 관리합니다. 유의미한 관계가 나타나지 않더라도 결과를 삭제하거나 가설을 변경하지 않습니다. 단, 실제 분석 결과 및 계수는 원자료 수집·검증 후에만 보고합니다.

## 실행 현황 (2026-11-06)

M0~M7 완료. 4종 원본의 스테이징·지역/연령 완전성·해시를 확인해 228지역·18필드의 분석 데이터를 만들었다(결측 0건). 공식 실제투표율 표와 전국·시도 계수를 직접 대조했다. 사전투표 분석표의 1,011명 차이는 공식 주석의 교부수/개표 기준 차이로 기록했고 분석 분자는 기존 개표 기준으로 유지했다. 지역별 조정은 동일 개표 원본을 재사용하므로 독립 재검증과 구별한다.

M3에서는 기술통계·상관·산점도와 원본 후보를 검수하고 모든 지역을 유지했다. G-M4-01의 인공 모형 검증 당시 전체 테스트 141개·Ruff·컴파일이 통과했다. G-M4-02에서는 생산 코드 변경 없이 make analyze를 실행했으며, 실제 8개 모형의 330개 수치와 표본 명단 1,824행을 별도 계산으로 대조했다. 이번 실제 결과 검수에서 프로젝트 단위 테스트를 다시 실행한 것은 아니다.

H1은 단순 M1에서 양의 관계가 관찰됐으나 통제 후 일관된 지지는 확보되지 않았다. H2는 M2·M3에서 예상과 반대 방향이며 M4에서는 음의 점추정이지만 95% CI가 0을 포함해 명확한 지지 근거가 부족하다. 이는 효과가 0이라는 증명이나 인과·개인 행동에 대한 결론이 아니다. 실제 표와 해석은 로컬 `outputs/hypothesis_results.md`, 검수 증거는 `outputs/model_validation.json`에 있다. G-M5-01에서 가중치·공통표본·특수지역 감도를 비교했고 G-M5-02에서 공선성·영향점·시도별 잔차를 점검했다. G-M5-03은 기본 M4의 226개 지역에서 탐색적 상호작용을 평가했다. 상세 결과는 로컬 `outputs/robustness_notes.md`에 있으며 [보고서 검수본](docs/REPORT.md)의 인용·수치 검수를 마쳤으며 G-M7-01은 별도 AI 검증자가 새 체크아웃·가상환경에서 직접 재실행해 완료했다. 테스트 141개·Ruff·컴파일이 통과했고 데이터/공식 대조 CSV 6개와 표/그림 21개가 보관본과 일치했다. 동일 호스트의 별도 에이전트 검증이며, 다른 사람·기기 또는 독립 실증자료에 의한 검증은 아니다. 환경·명령·검증자 기록은 로컬 `outputs/reproduction/README.md`에 있다. G-M7-02에서 로컬 최종 보고서와 공유 범위를 확정했다. 최종본은 `outputs/report/FINAL_REPORT.md`, M6 검수 기준본은 `docs/REPORT.md`에 있다. 상세 증거는 [연구기록](docs/RESEARCH_LOG.md), [출처 대장](docs/SOURCES.md), [로드맵](docs/ROADMAP.md)을 따른다.

재실행의 수행자와 수락 기록의 검토자는 모두 AI 에이전트다. 사람이 결과를 별도로 확인한 기록은 없으므로 제출이나 공개 전에 연구자가 직접 확인해야 한다. 2026-11-10 후속 정리 내역은 [연구기록](docs/RESEARCH_LOG.md)에 있으며 분석값은 바뀌지 않았다.

사전 계획 외 탐색 분석(G-POST-02)에서 M4의 계수를 나이 구성 몫과 같은 나이대 차이 몫으로 나눴다. X2 −0.070은 나이 구성 −0.100과 같은 나이대 차이 +0.030의 합이며, 나이 구성 몫은 계산값이고 같은 나이대 차이의 구간은 0을 포함한다. 지역 간 투표율 차이의 대부분은 나이 구성으로 설명되지 않았다. H1·H2 판정은 바뀌지 않았다. 상세 내용과 한계는 [보충 보고서](docs/SUPPLEMENT_DECOMPOSITION.md)에 있다.
