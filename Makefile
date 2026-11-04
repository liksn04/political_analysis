.PHONY: install lint test build explore analyze

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check src tests

test:
	python -m pytest

build:
	python -m political_analysis.pipeline --input-dir data/interim --crosswalk data/reference/region_crosswalk.csv --output data/processed/analysis_dataset.csv --report outputs/data_quality.json

explore:
	python -m political_analysis.exploration --data data/processed/analysis_dataset.csv --quality-report outputs/data_quality.json --output-dir outputs

analyze:
	python -m political_analysis.models --data data/processed/analysis_dataset.csv --output-dir outputs
