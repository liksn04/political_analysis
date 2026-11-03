.PHONY: install lint test build analyze

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check src tests

test:
	python -m pytest

build:
	python -m political_analysis.pipeline --input-dir data/interim --crosswalk data/reference/region_crosswalk.csv --output data/processed/analysis_dataset.csv --report outputs/data_quality.json

analyze:
	python -m political_analysis.models --data data/processed/analysis_dataset.csv --output-dir outputs
