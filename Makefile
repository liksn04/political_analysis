.PHONY: install lint test build explore analyze decompose audit-decomposition

# 보관 증거(outputs/data_quality.json, outputs/tables 등)를 덮어쓰지 않도록
# 현재 코드의 실행 결과는 별도 폴더에 둔다. 결정 근거: docs/DECISIONS.md ADR-013
RUN_DIR ?= outputs/current

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check src tests scripts

test:
	python -m pytest

build:
	python -m political_analysis.pipeline --input-dir data/interim --crosswalk data/reference/region_crosswalk.csv --output $(RUN_DIR)/analysis_dataset.csv --report $(RUN_DIR)/data_quality.json --reconciliation-output $(RUN_DIR)/official_reconciliation.csv

explore:
	python -m political_analysis.exploration --data $(RUN_DIR)/analysis_dataset.csv --quality-report $(RUN_DIR)/data_quality.json --output-dir $(RUN_DIR)

analyze:
	python -m political_analysis.models --data $(RUN_DIR)/analysis_dataset.csv --quality-report $(RUN_DIR)/data_quality.json --output-dir $(RUN_DIR)

# 사전 계획 외 탐색 분석 (docs/DECISIONS.md ADR-014). build 후 실행한다.
decompose:
	python -m political_analysis.decomposition --data $(RUN_DIR)/analysis_dataset.csv --quality-report $(RUN_DIR)/data_quality.json --output-dir $(RUN_DIR)

audit-decomposition:
	python scripts/audit_decomposition.py --run-dir $(RUN_DIR)
