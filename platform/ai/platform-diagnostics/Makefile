PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
DEPS_STAMP := $(VENV)/.contract-test-deps
TEST_REQUIREMENTS := contract/tests/requirements.txt

.DEFAULT_GOAL := verify

.PHONY: help verify contract-test clean

help:
	@echo "  make verify         Run the provider-neutral ADR-021 contract suite"
	@echo "  make contract-test  Alias for verify"
	@echo "  make clean          Remove the local test environment"

$(DEPS_STAMP): $(TEST_REQUIREMENTS)
	@$(PYTHON) -m venv $(VENV)
	@$(VENV_PYTHON) -m pip install -q --upgrade pip
	@$(VENV_PYTHON) -m pip install -q -r $(TEST_REQUIREMENTS)
	@touch $(DEPS_STAMP)

verify: $(DEPS_STAMP)
	@$(VENV_PYTHON) -m unittest discover -s contract/tests -p 'test_*.py' -v

contract-test: verify

clean:
	@$(PYTHON) -c 'import pathlib, shutil; shutil.rmtree(pathlib.Path("$(VENV)"), ignore_errors=True)'
