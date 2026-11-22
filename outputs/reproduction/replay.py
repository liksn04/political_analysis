"""Replay G-M7-01 in a temporary checkout and a fresh environment."""

import hashlib
import io
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
AUDIT = OUT / "reproduction"
DATA = Path("data/processed/analysis_dataset.csv")
BASE = "39e4e06021395adb7b2494f456c5e2f09fcb1f1a"
ATOL, RTOL = 1e-9, 1e-8


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def replay():
    original = load(OUT / "data_quality.json")
    m6 = load(OUT / "report/m6_review_validation.json")
    assert sha(ROOT / DATA) == original["dataset_sha256"] == m6["dataset_sha256"]
    assert sha(ROOT / "docs/REPORT.md") == m6["report_sha256"]
    assert sha(ROOT / "docs/SOURCES.md") == m6["source_log_sha256"]
    audit_scripts = ["exploration", "model", "robustness", "diagnostics", "interaction"]
    expected = {
        "exploration": "exploration_validation.json",
        "model": "model_validation.json",
        "robustness": "robustness_validation.json",
        "diagnostics": "diagnostics_validation.json",
        "interaction": "interaction_validation.json",
    }
    dependencies = {
        name: sha(OUT / f"{name}_audit.py")
        for name in audit_scripts
    }
    for name, manifest_name in expected.items():
        old = load(OUT / manifest_name)
        assert old["dataset_sha256"] == original["dataset_sha256"]
        assert old.get("audit_code_sha256", old.get("code_sha256")) == dependencies[name]
        for artifact, digest in old.get("artifacts", {}).items():
            assert sha(OUT / artifact) == digest
    assert sha(OUT / "tables/robustness_comparisons.csv") == load(
        OUT / "robustness_validation.json"
    )["comparison_table_sha256"]
    old_code = subprocess.check_output(
        ["git", "show", f"{BASE}:src/political_analysis/pipeline.py"], cwd=ROOT
    )
    data_key, = (
        Path(path) for path, digest in original["verified_files"].items()
        if Path(path).parts[-len(DATA.parts):] == DATA.parts and digest == original["dataset_sha256"]
    )
    archive_root = data_key.parents[len(DATA.parts) - 1]
    pipeline_file = Path("src/political_analysis/pipeline.py")
    for path, digest in original["verified_files"].items():
        relative = Path(path).relative_to(archive_root)
        actual = hashlib.sha256(old_code).hexdigest() if relative == pipeline_file else sha(ROOT / relative)
        assert actual == digest, relative

    with TemporaryDirectory(prefix="political-m7-") as temp:
        folder = Path(temp).resolve()
        archive = subprocess.check_output(["git", "archive", BASE], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as archive_file:
            archive_file.extractall(folder, filter="data")
        env = dict(os.environ)
        env.update(PYTHONPATH=str(folder / "src"), MPLCONFIGDIR=str(folder / ".mpl"), MPLBACKEND="Agg")
        env.pop("VIRTUAL_ENV", None)
        env.pop("PYTHONHOME", None)
        commands = []

        def run(*args, expected_error=None):
            args = [str(arg) for arg in args]
            cmd = shlex.join(args)
            commands.append(cmd)
            print("$", cmd, flush=True)
            p = subprocess.run(args, cwd=folder, env=env, capture_output=True, text=True)
            if p.stdout:
                print(p.stdout, end="", flush=True)
            if p.stderr:
                print(p.stderr, end="", flush=True)
            if expected_error:
                assert p.returncode != 0 and expected_error in p.stderr
            else:
                p.check_returncode()
            return p.stdout.strip()

        run("git", "apply", AUDIT / "certificate-path.patch")
        run("uv", "venv", "--python", Path(sys.executable).resolve(), ".venv")
        python = folder / ".venv/bin/python"
        run("uv", "--no-cache", "pip", "sync", "--python", python, AUDIT / "requirements-macos-arm64.txt")
        versions = json.loads(run(
            python, "-c", "import json,sys,numpy,pandas,statsmodels,matplotlib; "
            "print(json.dumps(dict(python=sys.version.split()[0], numpy=numpy.__version__, "
            "pandas=pandas.__version__, statsmodels=statsmodels.__version__, matplotlib=matplotlib.__version__)))"
        ))
        run(python, "-m", "pytest")
        run(python, "-m", "ruff", "check", "src", "tests")
        run(python, "-m", "compileall", "-q", "src")

        # A byte-identical CSV and its archived certificate are insufficient in another checkout.
        shutil.copy2(ROOT / DATA, folder / DATA)
        shutil.copy2(OUT / "data_quality.json", folder / "outputs/data_quality.json")
        assert not any((folder / "data/raw").glob("*.csv"))
        run(python, "-m", "political_analysis.exploration", expected_error="현재 분석 데이터 경로")
        (folder / DATA).unlink()
        (folder / "outputs/data_quality.json").unlink()
        assert not (folder / "outputs/tables").exists()

        for name in ["raw", "reference"]:
            shutil.copytree(ROOT / "data" / name, folder / "data" / name, dirs_exist_ok=True)
        shutil.copy2(OUT / "region_mapping_checks.json", folder / "outputs")
        for name in audit_scripts:
            shutil.copy2(OUT / f"{name}_audit.py", folder / "outputs")
        sources = [
            ("election", "제21대 대통령선거 개표결과.csv", []),
            ("population", "202505_202505_연령별인구현황_월간.csv", []),
            ("fiscal", "lofin365_2025_A137_gov.json", []),
            ("migration", "시군구별_이동자수_20261103170549.csv",
             ["--midyear-source", "data/raw/시군구_성_연령_1세_별_주민등록연앙인구_2023__20261103170428.csv"]),
        ]
        for dataset, source, extra in sources:
            run(python, "-m", "political_analysis.staging", "--dataset", dataset,
                "--source", "data/raw/" + source, *extra)
        run(python, "-m", "political_analysis.pipeline")
        certificate = load(folder / "outputs/data_quality.json")
        assert all(Path(path).is_relative_to(folder) for path in certificate["verified_files"])
        assert str((folder / DATA).resolve()) in certificate["verified_files"]
        run(python, "-m", "political_analysis.exploration")
        run(python, "-m", "political_analysis.models")
        run(python, "outputs/exploration_audit.py")
        run(python, "outputs/model_audit.py")

        validation = folder / "outputs/model_validation.json"
        checked = load(validation)
        old = load(OUT / "model_validation.json")
        assert old["text_review"] == "PASS"
        old_hypothesis = pd.read_csv(OUT / "tables/hypothesis_evaluation.csv")
        new_hypothesis = pd.read_csv(folder / "outputs/tables/hypothesis_evaluation.csv")
        pd.testing.assert_frame_equal(old_hypothesis, new_hypothesis, atol=ATOL, rtol=RTOL)
        note = OUT / "hypothesis_results.md"
        assert sha(note) == old["artifacts"][note.name]
        shutil.copy2(note, folder / "outputs")
        checked["text_review"] = "PASS"
        checked["artifacts"][note.name] = sha(note)
        validation.write_text(json.dumps(checked, ensure_ascii=False, indent=2) + "\n")
        for name in ["robustness", "diagnostics", "interaction"]:
            run(python, f"outputs/{name}_audit.py")

        exact = [DATA, Path("outputs/official_reconciliation.csv")]
        exact += [Path("data/interim") / f"{name}.csv" for name, _, _ in sources]
        for path in exact:
            assert sha(ROOT / path) == sha(folder / path), path
        files = sorted((OUT / "tables").glob("*.csv")) + sorted((OUT / "figures").glob("*.png"))
        comparisons = {}
        for current in files:
            name = current.relative_to(ROOT)
            new = folder / name
            same = sha(current) == sha(new)
            if current.suffix == ".csv":
                a = pd.read_csv(current)
                b = pd.read_csv(new)
                pd.testing.assert_frame_equal(a, b, atol=ATOL, rtol=RTOL)
                floats = a.select_dtypes("floating").columns
                pd.testing.assert_frame_equal(a.drop(columns=floats), b.drop(columns=floats), check_exact=True)
            elif not same:
                review = AUDIT / "figures" / new.name
                review.parent.mkdir(exist_ok=True)
                shutil.copy2(new, review)
            comparisons[str(name)] = {"baseline_sha256": sha(current), "replay_sha256": sha(new), "byte_identical": same}

        return {
            "gate": "G-M7-01", "baseline_code_commit": BASE, "report_sha256": m6["report_sha256"],
            "dataset_sha256": certificate["dataset_sha256"], "certificate_path_patch_sha256": sha(
                AUDIT / "certificate-path.patch"
            ),
            "requirements_sha256": sha(AUDIT / "requirements-macos-arm64.txt"),
            "platform": platform.platform(), "fresh_environment": versions, "tolerances": {"atol": ATOL, "rtol": RTOL},
            "certificate_paths_bound_to_replay": len(certificate["verified_files"]),
            "foreign_certificate_rejected": True, "audit_scripts": dependencies,
            "input_hashes": {str(Path(name).relative_to(folder)): digest for name, digest in certificate["verified_files"].items()},
            "identical_stage_dataset_reconciliation": {str(path): sha(folder / path) for path in exact},
            "output_comparisons": comparisons, "commands": commands, "third_party_replay": "pending",
        }


if __name__ == "__main__":
    result = replay()
    path = AUDIT / "replay_validation.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    outputs = result["output_comparisons"]
    print("Compared", len(outputs), "tables and figures. Byte differences:",
          [name for name, value in outputs.items() if not value["byte_identical"]], flush=True)
