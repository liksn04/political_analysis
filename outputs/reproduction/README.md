# G-M7-01 별도 환경 재실행 안내

재실행 도구는 기준 커밋 `39e4e06021395adb7b2494f456c5e2f09fcb1f1a`에서 임시 작업 폴더를 만들고 `certificate-path.patch`를 적용한다. macOS arm64의 Python 3.12.12에서 관측된 패키지 버전은 `requirements-macos-arm64.txt`에 고정했다.

별도 수행자의 체크아웃에 [인계 목록](handoff_manifest.json)과 목록에 적힌 71개 파일을 동일한 상대경로로 배치한다. 원본은 [공식 자료 대장](../../docs/SOURCES.md)의 조회 조건과 해시를 확인해 확보한다. 지역 참조자료와 비교용 산출물은 연구자가 확인한 전달 범위에 따라 배치한다.

저장소 루트에서 파일과 기준 커밋을 점검한 후 별도 수행자의 식별명으로 실행한다.

```bash
python3 outputs/reproduction/operator_replay.py --check-only
uv venv --python 3.12.12 .m7-bootstrap
uv pip sync --python .m7-bootstrap/bin/python outputs/reproduction/requirements-macos-arm64.txt
UV_HTTP_TIMEOUT=12 UV_HTTP_RETRIES=1 UV_NATIVE_TLS=true \
  .m7-bootstrap/bin/python outputs/reproduction/operator_replay.py --operator '검토자 식별명' \
  > outputs/reproduction/operator_run.log 2>&1
```

재실행용 가상환경은 부트스트랩과 별개로 만들고 `uv --no-cache pip sync`로 패키지를 설치한다. 별도 수행자는 `operator_replay_result.json`과 `operator_run.log`를 연구자에게 전달한다. 연구자는 수행자와 실행 환경, 인계 목록·데이터·검수본 해시, 복사 인증서 거부 기록, 수치·그림 대조 결과를 확인해 G-M7-01을 마감한다. 실행 스크립트는 결과를 검토 대기로 기록한다.

기존 분석과 보고서에 연결된 인증서는 해당 실행의 보관본이다. 현재 코드로 분석을 다시 실행할 때는 실제 입력과 실행 코드가 있는 경로에서 `make build`로 인증서를 발급한 뒤 탐색·회귀를 실행한다. 2026-11-10부터 `make`의 기본 출력은 `outputs/current/`이므로 같은 폴더에서 실행해도 보관본을 덮어쓰지 않는다. 비교용 보관본은 별도 경로에서 사용한다. `outputs/*_audit.py`까지 실행하려면 위 절차로 별도 체크아웃에서 실행한다.

## 관찰 결과

자체 재실행에서 새 가상환경의 테스트 141개, Ruff, 컴파일이 통과했다. 원자료가 없는 체크아웃에서 복사 인증서가 거부됐고, 해당 체크아웃에 원자료와 참조자료를 넣고 새로 발급한 인증서의 29개 경로는 모두 그 작업 폴더에 있었다. 표준 CSV 4개, 분석 CSV, 공식 대조 CSV와 표·그림 21개가 보관본과 바이트 단위로 일치했다. [비교·환경·해시 기록](replay_validation.json) · [실행 로그](run.log)

자체 재실행 당시 첫 패키지 설치 시도는 대기 끝에 중단했다. 설치 타임아웃·재시도 횟수·시스템 TLS를 지정한 두 번째 시도에서 새 환경을 구성했다. 위 내용과 `replay_validation.json`·`run.log`는 2026-11-04 자체 재실행 이력이다.

## 2026-11-06 별도 AI 검증자 재실행

별도 수행자 `/root/m7_independent_verifier`가 새 로컬 체크아웃과 Python 3.12.12 가상환경에서 문서화된 절차를 직접 실행했다. macOS arm64의 동일 호스트를 사용했으며, 다른 사람·다른 기기·다른 OS 또는 독립 실증자료의 검증은 아니다.

인계 71개 파일 점검, 고정 의존성 26개 캐시 없는 설치, 테스트 141개·Ruff·컴파일, 스테이징부터 공식 대조·탐색·회귀·강건성까지 통과했다. 표준 CSV 4개·통합 CSV·공식 대조 CSV와 표/그림 21개가 모두 보관본과 바이트 단위로 일치했다. 수치 허용오차는 절대 1e-9·상대 1e-8이며 식별자·정수는 정확히 대조했다. 복사 인증서는 거부됐고 새 인증서의 29개 경로가 해당 실행 폴더에 연결됐다.

- [수행자 원본 결과](operator_replay_result.json) · [실제 실행 로그](operator_run.log)
- [별도 검증자 검토](independent_verifier_review.md) · [증거 대조·수락 기록](operator_review_acceptance.json)

수행자 원본 결과의 `submitted_for_review`는 보존하고 수락 판정은 별도 기록에 둔다. 기존 `handoff_validation.json`의 `pending`과 `final_review_preflight.md`의 이전 대기 기록은 실행 전 이력이다. 보고서·출처 대장과 인계 목록의 해시는 유지했으며 본문 검수 기록 재사용은 새로운 문헌·본문 검증으로 간주하지 않는다. 이 기록 시점에 G-M7-01은 DONE, G-M7-02는 DRAFT였고, G-M7-02는 같은 날 완료했다.

수락 기록의 검토자는 구현 담당 AI 에이전트(`/root`)이며, 사람 연구자가 별도로 확인한 기록은 없다.
