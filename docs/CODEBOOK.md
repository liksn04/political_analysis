# 데이터 코드북

## 표준화된 입력 파일 (원본 다운로드 파일 아님)

모든 CSV는 UTF-8, 첫 줄은 헤더입니다. `source_region_code`와 `region_code`는 **문자열**로 취급하고 앞자리 0을 보존합니다. 빈 파일은 분석이 되지 않습니다.

### `data/interim/election.csv`

| 열 | 의미 | 조건 |
|---|---|---|
| source_region_code | 원자료 지역코드 | 같은 집계 수준에서 고유 |
| electors | 해당 원본 지역의 선거인수 | 양의 정수 |
| voters | 해당 지역 투표자수 | 0 이상, 선거인수 이하 |
| reported_turnout | 원본에 제공된 투표율(선택) | 0~100, 합산에 사용 안 함 |

`reported_turnout`은 열 자체를 생략하거나 빈 필드(공백만 있는 필드 포함)로 둘 수 있습니다. 비어 있지 않은 `NA`, `NaN`, `null`, 일반 문자열은 결측으로 간주하지 않고 오류로 처리합니다. 무한대와 0~100 밖 수치도 거부합니다. 원본의 결측기호는 출처별 변환 단계에서 확인한 뒤 빈 필드로 정규화합니다.

상하위 집계 행을 **동시에 포함하면 합계가 잘못되므로 금지**합니다. 선거인수와 투표자수가 동일 범위·동일 집계 수준인지 확인하세요.

### `data/interim/population.csv`

| 열 | 의미 |
|---|---|
| source_region_code | 주민등록 원본 지역코드 |
| age | 만 나이 (정수, 0~130) |
| population | 해당 연령 인구(정수, 0 이상) |

2025년 5월 기준으로 0세 이상을 모두 포함해야 총인구와 log_population을 구할 수 있습니다. `100세 이상` 같은 개방연령구간은 **하한 나이 100**으로 인코딩할 수 있지만, 그 구간을 별도의 100세 단일연령 값과 중복해서 입력해서는 안 됩니다.

### `data/interim/fiscal.csv`

| 열 | 의미 |
|---|---|
| source_region_code | 재정통계 원본 지역코드 |
| fiscal_independence | 2025 당초예산 재정자립도(%) |

동일 분석단위로 대응되는 값이 반드시 **한 건**이어야 합니다. 서로 다른 구의 비율을 합산·단순평균하지 않습니다.

### `data/interim/migration.csv`

| 열 | 의미 |
|---|---|
| source_region_code | 국내인구이동통계 원본 지역코드 |
| net_migrants | 2024년 순이동자수 (음수 가능) |
| midyear_population | 2024년 연앙인구 (양수) |

같은 분석단위로 들어오는 서로 다른 하위 단위들은 분자·분모를 각각 합산한 뒤 순이동률을 계산합니다.

### `data/reference/region_crosswalk.csv`

| 열 | 의미 |
|---|---|
| dataset | election / population / fiscal / migration |
| source_region_code | 각 입력 CSV의 원본 코드 |
| region_code | 연구의 기준 지역코드 (2025년) |
| region_name | 연구의 기준 지역명 |
| province | 광역시도 |
| region_type | `시`, `군`, `자치구`, `특수지역` |

(`dataset`, `source_region_code`) 조합은 고유해야 하며 각 입력의 모든 원본 코드는 정확히 한 개 분석 지역으로 대응되어야 합니다. 동일 `region_code`에는 모든 데이터셋에서 동일한 이름·시도·유형을 지정합니다.

## 최종 분석 데이터셋

| 필드 | 의미 / 계산 |
|---|---|
| region_code, region_name, province, region_type | 지역 식별 및 범주 |
| electors, voters | 선거 집계 계수 |
| turnout | 100 × voters / electors |
| population_total | 2025-05 주민등록 전체 인구 |
| population_18plus | 18세 이상 |
| population_65plus | 65세 이상 |
| population_80plus | 80세 이상 |
| aging_rate | 100 × population_65plus / population_18plus |
| oldest_share | 100 × population_80plus / population_65plus |
| fiscal_independence | 2025년 재정자립도 |
| net_migrants, midyear_population | 2024년 이동·연앙인구 |
| net_migration_rate | 100 × net_migrants / midyear_population |
| log_population | ln(population_total) |

## 품질관리

- 지역-원본코드 결합: 미대응 0건, 대응표 중복 0건
- 선거: `0 ≤ voters ≤ electors`, `electors > 0`
- 인구: `0 ≤ P80 ≤ P65 ≤ P18 ≤ Ptotal`, `P65 > 0`
- 산출 투표율: 0~100, 원본에 신고된 지역 투표율이 있다면 반올림 수준에서 비교
- 통제변수: 누락 빈도·특수지역 비교가능성 기록. 누락된 통제변수를 임의로 채우지 않음
- 표본: 핵심 결합 데이터에 필요한 지역이 빠지면 실패하도록 설정

검증 코드는 **원본 파일의 집계범위가 애초에 올바른지는 자동으로 입증하지 못합니다**. 수집자가 공식 통계 합계, 국내·국외선거 귀속, 일반구 중복 여부를 별도 확인해야 합니다.

## 2026-11-03 확정 지역 참조자료 (G-M2-01)

- `data/reference/expected_regions.csv`: 입력의 합집합에서 만들지 않고 행안부 공식 발간물의 시군구 명단(인쇄 6~14쪽)을 먼저 추출했다. 인쇄 4쪽의 시 75·군 82·자치구 69와 대조하고 세종·통합 제주를 추가해 228개로 확정했다. 명부의 원문 기준일은 2024-12-31이며 2025-05 인구 원본의 광역·기초단체 이름·코드와 전건 대조했다. 이는 경계 도형 대조까지 수행했다는 뜻은 아니다.
- 연구 `region_code`는 검증된 2025-05 행안부 10자리 코드이며 특수지역은 세종 `3600000000`, 제주 `5000000000`이다. 기존 표준 입력 스키마를 유지한다.
- `region_crosswalk.csv`: 4개 표준 입력용 937개 대응(선거 253, 인구·재정·이동 각 228). 선거는 원본에 숫자 코드가 없어 `시도명|구시군명`을 원본 필드의 복합 키로 사용한다. 재정은 원본 `lafNm`을 식별자로 쓴다. 이들을 제공기관의 공식 숫자 코드라고 부르지 않는다. 변환 단계에서도 같은 키를 재현해야 한다.
- 대응표 작성은 광역 소속·정확한 지역명·계층·공식 독립 명부를 모두 대조했으며 문자열 유사도나 숫자 일괄 치환으로 추측하지 않았다. 공백 제거는 원본 표시 정규화로만 사용했고 원문은 대장에 유지했다. 이동자료 5자리 행정코드는 행안부 10자리의 접미 0 정규화 후 지역명도 정확히 대조했다.
- `midyear_region_crosswalk.csv`: 연앙인구 통계분류 코드 전용 동반 대장. 표준 pipeline의 dataset 열에 다섯 번째 자료를 추가하지 않는다. 이동 스테이징에서 순이동·연앙인구를 검증된 연구 지역으로 각각 매핑한 뒤 하나씩 대응시킨다. 선택 행은 228개이며 반명 단위를 보존한다.
- `region_source_inventory.csv`: 포함·제외 사유가 있는 원본 지역 대장. 인구·이동·연앙인구는 상위 시/특수지역 값이 있으면 일반구·제주 행정시·세종 중복 행을 함께 더하지 않는다. 광역 합계(세종·제주 제외)·전국 합계·출장소를 제외한다. 이동자료의 25개 폐지/과거 코드는 2025 명부에 없고 해당 2024년 8개 항목이 모두 0임을 확인한 후 제외했다. 현행 지역의 실제 0명은 제외하지 않는다.
- 화성시갑·을은 원본의 일반투표 읍면동 집합이 19개·10개로 서로 겹치지 않고 공식 발간물 인쇄 94~95쪽의 29개와 정확히 일치한다. 계수 합산은 G-M2-02에서 수행하며 이번 검증을 선거 합계 일치로 간주하지 않는다.
- 검증 증거는 `outputs/region_mapping_checks.json`. 참조자료는 현재 Git 비추적 정책 안에 있으며 이 파일들의 존재만으로 공식 집계·연령·모형 검증 완료를 선언하지 않는다.

### 선거 원본 변환 실행 (G-M2-02)

`python -m political_analysis.staging --source "data/raw/제21대 대통령선거 개표결과.csv"`로 원본의 선거인수·투표수 항목을 표준 election.csv로 변환한다. 원본 문맥은 시도·구시군·읍면동·투표구로 식별하며 같은 문맥/항목의 중복이나 한쪽 계수 누락은 실패한다. 투표구명 없는 행은 실제 확인한 거소·선상투표/관외사전투표/재외투표/잘못 투입·구분된 투표지만 허용한다. 선거구별 원본 키를 보존하고 시 통합은 이후 파이프라인에서 한다. 산출물은 data/interim/election.csv 및 outputs/election_staging_checks.json이며 공식 검증 플래그는 아직 False다.

### 인구 원본 변환 실행 (G-M2-03)

`python -m political_analysis.staging --dataset population --source "data/raw/202505_202505_연령별인구현황_월간.csv"`로 CP949 원본을 표준 `source_region_code,age,population`의 UTF-8 CSV로 변환한다. 기본 산출물은 `data/interim/population.csv`, 지역별 검사표 `outputs/population_staging_checks.csv`, 해시·범위 보고서 `outputs/population_staging_checks.json`이다. 기존 선거 명령은 `--dataset`을 생략해도 유지된다.

확인한 2025-05 원본은 0~99세·100세 이상 101개 구간이며 최고 구간은 age=100으로 인코딩한다. 월·열·지역 범위를 고정해 누락/중복과 개방구간 중복을 거부한다. 빈칸·무한대·음수·소수·잘못된 쉼표는 오류이며 0명은 정상이다. 포함/제외 대장에 없는 원본 지역을 자동으로 버리지 않는다. 모든 선택 지역의 연령 합계는 총인구·연령구간인구와 일치해야 한다.

보고서의 `expected_ages`는 이후 통합 파이프라인의 연령 완전성 계약으로 사용할 값이다. 스테이징 성공만으로 임의의 long CSV 변경이 자동 검증되는 것은 아니다. G-M2-06에서 보고서 해시와 실제 입력을 연결한다. 지역별 검사표의 P18/P65/P80와 최종 데이터의 집계를 대조해야 한다.

### 재정 원본 변환 실행 (G-M2-04)

`python -m political_analysis.staging --dataset fiscal --source data/raw/lofin365_2025_A137_gov.json`으로 표준 `data/interim/fiscal.csv`를 생성한다. 기본 정의 원본은 `data/raw/lofin365_2025_A137_definition.json`이며, 정의·연도·당초·개편후·일반회계 기준과 원본 행의 표시 연도를 검사한다. 원본 행의 연도 공백은 새 연도를 추정하지 않고 보존된 조회조건·정의 파일을 근거로 기록한다.

확정 참조자료의 228개 대상에 지역당 한 값만 허용하며, 원본 243개 기관 중 제외한 광역 본청 15개는 기존 대장을 따른다. 원본 식별자 lafNm을 바꾸지 않는다. 동일 대상에 여러 원본 비율이 매핑되면 합산·평균하지 않고 실패시킨다. 출력의 원본값은 다시 계산하거나 반올림하지 않는다.

결측 계약은 ADR-007을 따른다. 값이 없는 행은 표준 CSV에서 생략하고 지역별 검사표 `outputs/fiscal_staging_checks.csv`에 `missing_source_value`로 기록한다. 통합 시 핵심 지역은 남고 재정 값만 결측이다. `outputs/fiscal_staging_checks.json`에는 원본·정의·대응표·대장·산출물 해시, 포함/제외/관측/결측 수를 기록한다. 보고서의 `independent_recalculation`은 별도 Decimal 검사에서 원본값 일치 및 자체수입/예산규모 비율의 표시 정밀도를 대조한 실행 증거다.

### 이동·연앙인구 변환 실행 (G-M2-05)

```bash
python -m political_analysis.staging --dataset migration \
  --source "data/raw/시군구별_이동자수_20261103170549.csv" \
  --midyear-source "data/raw/시군구_성_연령_1세_별_주민등록연앙인구_2023__20261103170428.csv"
```

분자·분모 모두 2024년 단일 연간 시점이어야 한다. 이동자료는 원본 8개 항목 구조와 순이동 T25를 확인하고, 음의 순이동은 유지하며 정수·전입/전출 비음수·순이동=전입-전출 관계를 검사한다. 연앙인구는 성별 계·연령별 계만 사용하고 원본의 양수 소수값을 보존한다. 2025-05 주민등록 전체 인구로 대체하거나 반명 단위를 정수로 반올림하지 않는다.

이동 원본 코드는 region_crosswalk.csv의 migration 대응을, 연앙인구 코드는 midyear_region_crosswalk.csv를 사용한다. 이름·행 순서·숫자 코드 치환으로 결합하지 않고 두 자료가 동일한 연구 지역 집합에 일대일로 대응해야 한다. 현재 참조자료는 직접 제공된 시/특수지역 총계만 선택하므로 하위 일반구·중복 총계를 다시 더하지 않는다. 다른 집계단위 자료를 쓰려면 참조 계약부터 다시 잠근다.

산출물은 data/interim/migration.csv(source_region_code,net_migrants,midyear_population), outputs/migration_staging_checks.csv, outputs/migration_staging_checks.json이다. 검사표는 두 원본 코드·연구 코드와 `100 × net_migrants / midyear_population`을 연결한다. JSON에는 양쪽 원본·참조·산출물 해시와 포함 지역 수를 기록한다. `independent_recalculation`은 본 회차의 별도 csv/int/Decimal 재대조 증거이며 CLI가 자동 계산한 값과 구별한다.

### 통합·공식 대조 실행 (G-M2-06)

`make build`는 기본적으로 독립 기대 지역 명부, 4종 스테이징 보고서의 원본/출력/참조 해시, 선언된 연령 목록을 확인한다. 핵심 원본 구역 누락, 양쪽 자료에서 같은 지역 누락, 지역 메타데이터 상충, 선언 연령 누락·추가·중복, 비유한 파생변수를 차단한다. 원본·표준 CSV·참조자료·검사표 또는 데이터 생성 코드가 바뀌면 기존 검증을 재사용하지 않는다.

결과는 `data/processed/analysis_dataset.csv`, `outputs/data_quality.json`, `outputs/official_reconciliation.csv`다. 분석 데이터는 228지역·18필드이며 개표 기준 voters는 원본 그대로 유지한다. 선택/집계/비율은 기존 프로토콜을 따른다. source 보고서 경로와 원본 경로는 연구 디렉터리 구조에 따라 연결한다.

공식 대조표는 전국 1·시도 17·원본 선거구역 253·연구 분석단위 228행, 총 499행이다. 서로 중첩되는 집계 수준이므로 모든 행을 합산하지 않는다. 전국·시도는 실제투표율 표의 실제 결과와 직접 비교한다. 원본/연구 지역 행에는 원래 값·사전투표 교부수/개표수 차이·조정값·조정 전후 잔차·비교 종류·원본 시트/행을 기록한다. 지역별 조정은 개표자료를 재사용하므로 독립적인 재검증이 아니다.

표시 투표율은 소수 첫째 자리 계약으로 확인하고 기존 0.11%p 상수는 폐기했다. 출력의 계산 투표율은 반올림하지 않는다. 품질보고서의 `official_election_totals_verified=True`는 직접 전국·시도 대조 및 주석에 따른 지역 범위 조정을 통과했다는 뜻이며 지역별 완전 독립 재검증을 뜻하지 않는다.

`verify_dataset_certificate(data_path, quality_path)`는 공식 대조·입력 계약 상태와 데이터 해시, 연결된 원본/참조/검사표/코드 해시를 다시 확인한다. 보고서의 True 값만으로 분석을 허용하지 않는다. 순수 인공 입력용 라이브러리 호출은 기본 내부 검사만 수행할 수 있으나 공식 대조 플래그는 False이며 분석 인증서로 사용할 수 없다. M3 실행 경로는 이 인증서 검사를 연결해야 한다.

별도 실제 복사본 오류 주입 및 결합값 재계산 증거는 `outputs/build_runtime_checks.json`에 보관했다. 원본을 수정하지 않는 임시 복사본에서만 변경·누락을 시험했다.

### 독립 탐색 실행 (G-M3-01)

`make explore` 또는 `python -m political_analysis.exploration --data data/processed/analysis_dataset.csv --quality-report outputs/data_quality.json --output-dir outputs`를 사용한다. 실제 입력/원본/참조/생성 코드와 데이터 해시를 인증서와 대조한 뒤 실행한다. 생략·미완료·변경된 인증서를 허용하는 우회 옵션은 없다. 파일 기반 회귀 진입점 make analyze도 같은 인증서를 먼저 요구한다.

탐색은 회귀를 호출하지 않고 숫자형 변수 기술통계·결측 수, Y/X1/X2 피어슨 상관행렬, 쌍별 유효 n·상태와 산점도를 생성한다. 식별자 region_code는 숫자형으로 주어져도 기술통계에서 제외한다. n<2 또는 상수 변수로 계산할 수 없는 상관은 NaN을 유지하고 insufficient_pairs/constant_variable로 표시한다. 점도표에는 회귀선을 넣지 않는다. 완전한 x/y 관측쌍이 없으면 이를 명시한 그림을 새로 생성해 오래된 그림과 구별한다.

exploration_manifest.json은 입력·품질보고서·탐색 코드·출력 해시와 유효 관측수, 함수 자체의 회귀 미실행 상태를 기록한다. 이는 결과의 인과 해석이나 전체 분석 작업의 회귀 미실행 증거로 확대하지 않는다. 실제 탐색 수치·그림·이상치 검수는 G-M3-02에서 별도로 수행한다.

### 정식 탐색 검수 (G-M3-02)

탐색 결과는 `outputs/exploration_notes.md`, 검수 증거는 `outputs/exploration_validation.json`에 고정했다. 감사 재현은 make explore 후 `.venv/bin/python outputs/exploration_audit.py`로 실행한다. 수치 재계산은 csv/statistics/math, 원본 후보 대조는 보존 원본·확정 대응표를 사용한다. 감사 스크립트와 QA 표는 기존 outputs 비추적 정책 안에서 보존하므로 M7 재현/공유 패키지에서 함께 취급한다.

IQR 후보와 핵심 극값은 점검 표식이며 표본 삭제나 영향점 판정이 아니다. 228개 지역을 모두 유지했다. 단순 상관은 비가중 지역 수준의 통제 전 관계이며 조건부 회귀·인과효과·개인 투표행동을 의미하지 않는다. 새로운 독립 자료를 수집한 것과 같은 원본을 다른 코드로 재대조한 것을 구별한다. 이미지 확인은 별도 실행 기록이며 감사 재실행 후 자동 완료로 간주하지 않는다.

### 모형 수치·표본 출력 (G-M4-01)

기존 fit_models(data)의 (coefficients, summary) 반환은 유지한다. fit_models_with_samples(data)는 같은 추정과 포함/제외 명단을 세 번째 표로 반환한다. 파일 실행 경로는 기존 인증서를 먼저 확인하고 model_coefficients.csv·model_summary.csv·model_samples.csv·model_notes.txt 및 model_manifest.json을 생성한다. manifest는 데이터·품질보고서·모형 코드·산출물 해시를 연결한다.

summary에는 모형식·n·후보/제외 수·설계 열·rank·모수 수·잔차 자유도·조건수·최대 leverage·기준범주·HC3/정규근사 CI 정보를 기록한다. condition_number와 leverage는 WLS에서 가중 설계행렬을 기준으로 한다. samples는 모든 입력 행에 대해 model·sample_id·row_position·지역명/시도/유형·included·exclusion_reason을 제공한다. sample_id_kind가 region_code인지 인공/메모리 위치 ID인지 구별한다.

공통표본은 M4 OLS의 사용 지역과 같으며 가중치 결측은 WLS에서만 해당 사유로 제외한다. 식별 불가·HC3 미정의·비유한 결과는 성공 표로 내보내지 않는다. 인공 수치 검증 결과는 outputs/model_contract_checks.json이며 실제 연구 회귀 결과가 아니다.

### 실제 모형 결과 검수 (G-M4-02)

실제 추정은 M1~M3 각 228지역, M4·선거인수 가중 WLS·M1_common~M3_common 각 226지역이다. 기본 OLS 4개와 보조 4개를 모두 보존했다. `outputs/hypothesis_results.md`는 계수·HC3 양측 정규근사 CI·p·표본 변화·해석 한계를, `tables/hypothesis_evaluation.csv`는 기본 모형의 H1/H2 평가 7행을 기록한다. 분모·변수·자료·사전 제외 정책은 변경하지 않았다.

`outputs/model_validation.json`은 실제 66개 term의 330개 숫자와 표본 명단 1,824행을 별도 행렬 계산으로 대조한 증거다. `model_contract_checks.json`의 인공 검증과 구별한다. 동일 자료에 대한 독립 산술 구현이며 독립 표본의 실증 재현은 아니다. `outputs/model_audit.py`로 재검사할 수 있고, 본문 검수는 별도로 기록한다. outputs의 비추적 정책은 유지하며 재현/공유 패키지는 M7에서 다룬다. 강건성 검토는 아직 미완료다.
