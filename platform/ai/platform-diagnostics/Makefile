PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
DEPS_STAMP := $(VENV)/.contract-test-deps
TEST_REQUIREMENTS := contract/tests/requirements.txt

# The normative contract the suites validate against. Set explicitly rather than
# resolved from the checkout, so that "which specification did this run test?" is
# answerable from the command line. The suites additionally pin info.version, so
# pointing this at an older contract fails instead of passing quietly.
OPENAPI_SPEC ?= $(CURDIR)/contract/openapi.yaml
export OPENAPI_SPEC

.DEFAULT_GOAL := verify

.PHONY: help check-python verify contract-test facade-test clean

help:
	@echo "  make verify         Run the provider-neutral ADR-021 contract suite"
	@echo "                     against every registered provider, then the"
	@echo "                     Profile A facade conformance tests"
	@echo "  make contract-test  Alias for verify"
	@echo "  make facade-test    Run Profile A facade conformance tests only"
	@echo "  make clean          Remove the local test environment"
	@echo ""
	@echo "  OPENAPI_SPEC=$(OPENAPI_SPEC)"

check-python:
	@$(PYTHON) -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required; set PYTHON=/path/to/python3.12"'

$(DEPS_STAMP): $(TEST_REQUIREMENTS) profiles/kagent/facade/requirements.txt | check-python
	@$(PYTHON) -m venv $(VENV)
	@$(VENV_PYTHON) -m pip install -q --upgrade pip
	@$(VENV_PYTHON) -m pip install -q -r $(TEST_REQUIREMENTS)
	@touch $(DEPS_STAMP)

verify: $(DEPS_STAMP)
	@$(VENV_PYTHON) -m unittest discover -s contract/tests -p 'test_*.py' -v
	@DIAGNOSTICS_BEARER_TOKEN=profile-a-contract-test \
		PYTHONPATH=profiles/kagent/facade \
		$(VENV_PYTHON) -m unittest discover \
		-s profiles/kagent/facade/tests -p 'test_*.py' -v

contract-test: verify

facade-test: $(DEPS_STAMP)
	@DIAGNOSTICS_BEARER_TOKEN=profile-a-contract-test \
		PYTHONPATH=profiles/kagent/facade \
		$(VENV_PYTHON) -m unittest discover \
		-s profiles/kagent/facade/tests -p 'test_*.py' -v

clean:
	@$(PYTHON) -c 'import pathlib, shutil; shutil.rmtree(pathlib.Path("$(VENV)"), ignore_errors=True)'
