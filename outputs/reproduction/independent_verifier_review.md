# G-M7-01 별도 검증자 검토

- 판정: **AC1 PASS / AC2 PASS / AC3 PASS**. 사용자 요청의 별도 AI 검증자 조건에 한정한다.
- 수행자: `m7_independent_verifier`, 에이전트 경로 `/root/m7_independent_verifier`.
- 독립성 범위: 구현 에이전트와 별개의 AI 에이전트가 같은 호스트에서 직접 명령을 실행했다. 다른 사람·다른 물리 기기·별도 실증자료의 검증이 아니다.
- 적용 계약: `docs/ROADMAP.md` G-M7-01 및 Standard 공통 계약, `document-gated-vibe-coding` v2.1. 검증 목표는 기존 계산 결과 없이 원본 입력부터 보고용 수치를 재현하는 것이다.
- 허용 범위: 별도 임시 clone/가상환경, 이 검토서와 `outputs/reproduction/`의 수행자 결과·로그·검증 증거. 원본 코드·상태 문서·연구설계·원본 자료는 변경하지 않았다. G-M7-02, 외부 게시·커밋·푸시는 범위 밖이다.
- 복구 원칙: 실패 시 새 실행 경로와 로그를 보존하고 원본을 수정하지 않는다. 이번 실행에는 실패나 코드 수정이 없었다.
- 시작/완료: `2026-11-06T01:44:31.667453+00:00` → `2026-11-06T01:45:41.566629+00:00`, operator PID `43994`, 종료코드 `0`.

## 환경과 경로

- 인계 체크아웃: `/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/checkout`
- 실제 분석 실행 경로: `/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1`. 스크립트의 정상 종료 때 임시 분석 경로는 정리됐다.
- 보존 증거: `independent_verifier_evidence/`와 그 아래 `generated/`. 읽기 전용 관찰자가 실행 도중 생성물을 복사했고, 종료 후 결과 JSON의 재실행 해시와 27개 파일 전부 일치함을 확인했다. 스크립트 자체는 수정하지 않았다.
- OS: `macOS-27.2-arm64-arm-64bit`. 분석 Python `3.12.12`. 기본 시스템 `python3`은 3.13.3으로 파일 준비와 check-only에만 사용했다.
- NumPy `2.5.4`, pandas `2.3.3`, statsmodels `0.15.0`, matplotlib `3.11.2`. 전체 26개 고정 패키지는 설치 로그와 requirements 파일에 기록되어 있다.
- 기준 커밋: `39e4e06021395adb7b2494f456c5e2f09fcb1f1a` + `certificate-path.patch`. 현재 작업트리의 추적 `src/`·`tests/` 11개 파일 모두 이 조합과 SHA-256이 같고, 두 경로의 추가 비추적 코드파일은 없었다.

## AC별 실제 결과

| 조건 | 결과 | 실행 증거 |
|---|---|---|
| AC1 모든 단계의 명령·입출력·해시 기록 | PASS | 공식 71개 파일과 기준 커밋 `--check-only` PASS. 기준 커밋+패치 확인 후 20개 내부 명령 실제 실행. 원본/참조/코드/데이터 29개 인증서 경로, 산출물별 해시와 환경은 `operator_replay_result.json`, 표준화→결합→공식 대조→탐색→회귀→강건성 로그는 `operator_run.log`에 기록. |
| AC2 사전 고정 오차 및 수치/바이트 차이 구분 | PASS | `atol=1e-9`, `rtol=1e-8`; 18개 CSV와 3개 PNG 모두 바이트 동일. 별도 후검사에서 CSV의 유한 숫자 6,503개 최대 절대차 0.0, 정수·문자·행/열 구조 정확 일치. |
| AC3 기존 결과 없는 경로 및 별도 수행자 | PASS | 새 git archive 경로와 새 venv, `uv --no-cache pip sync` 완료. 복사 인증서+CSV는 원자료 없이 거부됨을 실제 관찰한 뒤 삭제. 표준화 시작 전 표 디렉터리 부재 확인. 새로 발급한 인증서 29개 경로 모두 새 실행 경로 내부. 수행자·경로·OS·버전·실행 시간 별도 기록. |

- 전체 인공자료/코드 회귀 테스트: **141 passed in 19.23s**. 이는 실자료의 독립 공식 검증을 뜻하지 않는다.
- Ruff: **All checks passed!**. 컴파일 검사 종료코드 0. 기준 커밋+패치 작업트리 `git diff --check` PASS.
- 표준 CSV 4개, 분석 CSV, 공식 대조 CSV 총 6개: 보관본과 전부 SHA-256/바이트 동일.
- 실제 모형 별도 행렬 재계산: 330개 계수/표준오차/p/CI 셀, 1824개 표본 소속 행 확인. 보관본 대비 차이 0과 구별해야 하는 행렬 계산 방식 간 최대 절대차는 아래와 같다. 모두 고정 오차 안이다.

| 항목 | 별도 행렬 계산과 생산 결과의 최대 절대차 |
|---|---:|
| `estimate` | `5.5962345868465491e-11` |
| `std_error_hc3` | `8.5309537212197029e-12` |
| `p_value` | `6.6072702864516941e-12` |
| `ci_low` | `5.0292214837099891e-11` |
| `ci_high` | `7.2688521868258249e-11` |

## 생성물과 보관본의 경계

- 새로 계산: 네 표준 입력, 결합 데이터, 공식 대조, 탐색 통계·상관·극단값 점검, 회귀·HC3·CI·p·표본 명단·가설평가, 가중/공통표본 강건성, 영향점·VIF·감도분석, 상호작용 및 3개 그림.
- 전달받아 재사용한 입력: 동일 공식 원자료 8개와 지역 참조자료, `region_mapping_checks.json`. 공식 사이트에서 새로 취득하거나 지역 명부를 독립적으로 재구축하지 않았다.
- 비교 목적으로만 읽은 보관본: 기존 표준/분석 CSV, 표·그림, 과거 검수 JSON. 분석 경로에는 계산 결과를 미리 채우지 않았다. 복사 인증서 거부 실험에만 보관본 CSV와 인증서를 잠깐 복사한 뒤 삭제했다.
- 기존 문서 검수의 승계: `replay.py`는 새 `hypothesis_evaluation.csv`의 일치와 기존 `hypothesis_results.md`의 해시를 확인한 뒤 문서 및 `text_review=PASS`를 새 검수 기록에 복사한다. 이는 이번 에이전트가 본문·인용 전체를 새로 검수했다는 뜻이 아니다. `docs/REPORT.md`/`SOURCES.md`는 M6 검수본 해시 일치를 확인했다.
- 시각 검사: 보존한 실제 생성 PNG 3개를 이 검증자가 직접 열었다. 산점도의 65+/18+ 비율과 투표율 % 축, 영향점의 n=226·Cook/레버리지 임계선과 범례, 상호작용의 탐색 표시·95% 점별 CI·0 기준선·%p 단위 및 분포를 읽을 수 있었다. 글꼴 깨짐/제목·축 잘림을 발견하지 못했다.

## 실제 실행 명령

다음 준비 명령을 별도 체크아웃에서 수행했다. clone은 원본 작업트리를 변경하지 않으며, 인계 목록의 71개 파일 및 manifest/안내를 같은 상대경로로 `shutil.copy2`로 복사했다. bootstrap 및 분석 venv 모두 no-cache 설치가 실제 종료코드 0으로 완료됐다.

```bash
git clone --no-local --no-checkout '/Users/liksn04/Desktop/정치분석연구/political_analysis' /var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/checkout
git checkout --detach 39e4e06021395adb7b2494f456c5e2f09fcb1f1a
python3 outputs/reproduction/operator_replay.py --check-only
git apply --check outputs/reproduction/certificate-path.patch
git apply outputs/reproduction/certificate-path.patch
git diff --check
uv venv --python 3.12.12 .m7-bootstrap
uv --no-cache pip sync --python .m7-bootstrap/bin/python outputs/reproduction/requirements-macos-arm64.txt
UV_HTTP_TIMEOUT=12 UV_HTTP_RETRIES=1 UV_NATIVE_TLS=true TMPDIR=/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp .m7-bootstrap/bin/python outputs/reproduction/operator_replay.py --operator 'm7_independent_verifier (/root/m7_independent_verifier; same-host separate AI agent)' > outputs/reproduction/operator_run.log 2>&1
```

내부 재실행 명령(실행 결과는 로그 참조):

```bash
git apply /private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/checkout/outputs/reproduction/certificate-path.patch
uv venv --python /Users/liksn04/.local/share/uv/python/cpython-3.12.12-macos-aarch64-none/bin/python3.12 .venv
uv --no-cache pip sync --python /private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python /private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/checkout/outputs/reproduction/requirements-macos-arm64.txt
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -c 'import json,sys,numpy,pandas,statsmodels,matplotlib; print(json.dumps(dict(python=sys.version.split()[0], numpy=numpy.__version__, pandas=pandas.__version__, statsmodels=statsmodels.__version__, matplotlib=matplotlib.__version__)))'
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m pytest
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m ruff check src tests
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m compileall -q src
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m political_analysis.exploration
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m political_analysis.staging --dataset election --source 'data/raw/제21대 대통령선거 개표결과.csv'
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m political_analysis.staging --dataset population --source 'data/raw/202505_202505_연령별인구현황_월간.csv'
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m political_analysis.staging --dataset fiscal --source data/raw/lofin365_2025_A137_gov.json
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m political_analysis.staging --dataset migration --source 'data/raw/시군구별_이동자수_20261103170549.csv' --midyear-source 'data/raw/시군구_성_연령_1세_별_주민등록연앙인구_2023__20261103170428.csv'
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m political_analysis.pipeline
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m political_analysis.exploration
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python -m political_analysis.models
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python outputs/exploration_audit.py
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python outputs/model_audit.py
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python outputs/robustness_audit.py
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python outputs/diagnostics_audit.py
/private/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/replay-temp/political-m7-5s03t6_1/.venv/bin/python outputs/interaction_audit.py
```

추가 검증 명령: `/var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/checkout/.m7-bootstrap/bin/python /var/folders/v9/dpzwrlw96l55_trc9c5llkgh0000gn/T/m7-independent-verifier-pt6dy5g6/verify_generated.py`. 스크립트와 결과는 `independent_verifier_evidence/verify_generated.py`, `postcheck.json`에 보존했다.

## 주요 SHA-256

전체 인계 파일 해시는 `handoff_manifest.json`, 실제 인증서 입력 29개와 산출물 27개 해시는 수행자 결과/후검사 JSON에 있다.

| 대상 | SHA-256 |
|---|---|
| `docs/REPORT.md` | `aa5e31c162be05b6029b9835db1eb83cb76d86b170162f2e1d1293bb00cd25db` |
| `docs/SOURCES.md` | `207fe87a229eed42bc7570e8c5fb456d5c7cd94a0ca39ee02ab505e127d1f6aa` |
| `outputs/reproduction/handoff_manifest.json` | `4a52540265c307bdf22d5d2d66b61baaf845e01c8efbb18d28f982e2d95f08e4` |
| `outputs/reproduction/certificate-path.patch` | `d0b6d7a17f938d89cf3fa93d565236013413af56600d62de5203d54381410e10` |
| `outputs/reproduction/requirements-macos-arm64.txt` | `69a0364cb3b2bb179ba8fd074dc564b27f5988cbe1bf096ecf4dfb00aa4e30a7` |
| `outputs/reproduction/operator_replay.py` | `be3aeeaf4c3c94d5ae4ec9d7f2347cce693a4c1c40e538c37bb243f45fced98c` |
| `outputs/reproduction/replay.py` | `7679aa75a1b7913d7e1829f1fc2c453ed5d84ed5f04a09ff90520ae1c0843539` |
| `data/raw/202505_202505_연령별인구현황_월간.csv` | `3eff2a7faf75907b8cb62148d8f9fcabf06d3f37f7208df8641f69dcfe9bdc22` |
| `data/raw/lofin365_2025_A137_definition.json` | `1b6d56b2991135698cd7eb7da7afcee3122c4fa689ea78817c434dfca0d6880f` |
| `data/raw/lofin365_2025_A137_gov.json` | `2421e2731909ad86f86e04d66c96f909312a7805233a8099f3c7fb6c516c31de` |
| `data/raw/mois_2025_regions_20241231.pdf` | `e0df753e1cd3670513cb23a17fe97b57c2da75fe6bcfe4b6b91d3657838a9e21` |
| `data/raw/시군구_성_연령_1세_별_주민등록연앙인구_2023__20261103170428.csv` | `9cd454ab87ba71434640b98d1c3748b86d6b8a1c679fd82681877adde3bfe7c4` |
| `data/raw/시군구별_이동자수_20261103170549.csv` | `a16467c3da15380b89b2c9382139fca3dc24dddac8570e69d848df2eaa515af0` |
| `data/raw/제21대 대통령선거 개표결과.csv` | `4d1479e549e3ab0f6ae2a5b4436ec085f4326711a6a4163636be12a1a6e39e19` |
| `data/raw/제21대 대통령선거 투표율 분석.zip` | `3ae2d63dbad0b30072472cd4ff8a81c10a78c703d6bb53d2e4be17d3e8e7ccc3` |
| `data/reference/expected_regions.csv` | `ff406ebe006a07265db0df3dd70cda80b1afa4b174b541685989312458e85c40` |
| `data/reference/midyear_region_crosswalk.csv` | `809a3b2f1e256a5556550e722b33e9539d765deeae73d0314dc490da8f0fc661` |
| `data/reference/region_crosswalk.csv` | `15cb03ab589a7ce942e6735ca3204ffb47db9dd7efb8df9e5949f2fab5160bd9` |
| `data/reference/region_source_inventory.csv` | `2c151a080e94a16d902427e119c96e62535fe7c4a17d1f6e86181411851d5e7c` |
| `outputs/diagnostics_audit.py` | `62cea62623d7534d22ea39b965145bb79565b54acbe820bace2f7c77fbfb7024` |
| `outputs/exploration_audit.py` | `2fab680292a57cf8dd46cc1781314729d66377389708407dfab9b15f1681c2f5` |
| `outputs/interaction_audit.py` | `57c7671530bfd0d1e705fbb9e6a5f306f3bf7b92ef97d89bfb1202acf66cb563` |
| `outputs/model_audit.py` | `9213e0588cf1219dff704f0756d2057b09ac8dfa2fbcc2c725929965b137d3c0` |
| `outputs/robustness_audit.py` | `5c2933c7640fd7919e75776ec2b445e920c509c3742dd18435025c4adce8f403` |
| `operator_replay_result.json` | `20c74a8f38c4f2bb19d58c493bd741fcafbca45cccef7739b89564e1a5ede331` |
| `operator_run.log` | `8812cb1897abf78ba5524e8dc0eda1a4022e982e7d504e1f6a47a9035d7fb558` |

## 남은 한계와 인계

G-M7-01의 지정 환경·별도 AI 검증자 범위에서 필수 미실행 검사는 없다. 같은 호스트의 시스템 Python 배포본·OS·아키텍처를 공유하며 다른 OS/CPU/패키지 조합의 재현성, 다른 인간 검증자의 실행은 확인하지 않았다. 설치는 no-cache이지만 시스템 인터프리터를 새로 빌드한 것은 아니다. 원자료 자체의 진실성·독립 실증자료·공식 집계 조정의 외부 독립성·인과효과는 이 재실행으로 검증되지 않는다.

원본 재배포/외부 업로드와 최종 제출물 검수·공유범위 확정(G-M7-02)은 수행하지 않았다. 구현 담당자에게 수행자 원본 JSON(`status=submitted_for_review` 보존), 로그와 이 검토서를 인계한다. 상태 문서의 수락/마감은 구현 담당자가 이 증거를 확인한 뒤 별도로 기록한다.
