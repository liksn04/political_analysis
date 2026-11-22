"""Check the handoff inputs and record a separate operator's replay."""

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "handoff_manifest.json"
RESULT = HERE / "operator_replay_result.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(manifest):
    failures = []
    for relative, entry in manifest["files"].items():
        path = ROOT / relative
        if not path.resolve().is_relative_to(ROOT) or not path.is_file():
            failures.append(f"파일 누락 또는 작업 폴더 밖 참조: {relative}")
        elif sha(path) != entry["sha256"]:
            failures.append(f"해시 불일치: {relative}")
    if failures:
        raise SystemExit("\n".join(failures))
    subprocess.run(
        ["git", "cat-file", "-e", manifest["baseline_code_commit"] + "^{commit}"],
        cwd=ROOT,
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true", help="파일과 기준 커밋만 점검")
    mode.add_argument("--operator", help="재실행한 별도 수행자의 식별명")
    args = parser.parse_args()
    if args.operator is not None and not args.operator.strip():
        parser.error("수행자 식별명을 입력하세요.")
    manifest = json.loads(MANIFEST.read_text())
    preflight(manifest)
    print(f"인계 파일 {len(manifest['files'])}개와 기준 커밋 확인", flush=True)
    if args.check_only:
        return
    if RESULT.exists():
        raise SystemExit("기존 수행자 결과를 별도 보관한 뒤 새로 실행하세요.")

    from replay import replay

    result = replay()
    result["operator_evidence"] = {
        "identifier": args.operator.strip(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "handoff_manifest_sha256": sha(MANIFEST),
        "status": "submitted_for_review",
    }
    result.pop("third_party_replay", None)
    with RESULT.open("x") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"수행자 기록 저장: {RESULT}", flush=True)


if __name__ == "__main__":
    main()
