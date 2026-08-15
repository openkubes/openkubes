PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
DEPS_STAMP := $(VENV)/.dev-deps

.DEFAULT_GOAL := verify

.PHONY: check-python generate generate-check test syntax verify clean

check-python:
	@$(PYTHON) -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required; set PYTHON=/path/to/python3.12"'

$(DEPS_STAMP): requirements-dev.txt requirements.txt | check-python
	@$(PYTHON) -m venv $(VENV)
	@$(VENV_PYTHON) -m pip install -q -r requirements-dev.txt
	@touch $(DEPS_STAMP)

generate: $(DEPS_STAMP)
	@$(VENV_PYTHON) generate.py

generate-check: $(DEPS_STAMP)
	@$(VENV_PYTHON) generate.py --check

test: $(DEPS_STAMP)
	@$(VENV_PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

syntax: check-python
	@$(PYTHON) -c 'import ast, pathlib; [ast.parse(path.read_text(), filename=str(path)) for path in pathlib.Path(".").rglob("*.py") if ".venv" not in path.parts]'

verify: generate-check test syntax

clean:
	@$(PYTHON) -c 'import pathlib, shutil; shutil.rmtree(pathlib.Path("$(VENV)"), ignore_errors=True)'
