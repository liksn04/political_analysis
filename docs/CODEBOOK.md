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
