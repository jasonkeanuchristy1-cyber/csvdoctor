.PHONY: dev test lint build clean

dev:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check .

build:
	python -m build
	twine check dist/*

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache
