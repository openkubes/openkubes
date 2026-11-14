PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
DEPS_STAMP := $(VENV)/.deps

.DEFAULT_GOAL := verify

.PHONY: verify verify-measured static test syntax clean

$(DEPS_STAMP): requirements.txt
	@$(PYTHON) -m venv $(VENV)
	@$(VENV_PYTHON) -m pip install -q -r requirements.txt
	@touch $(DEPS_STAMP)

static: $(DEPS_STAMP)
	@$(VENV_PYTHON) verify.py

test: $(DEPS_STAMP)
	@$(VENV_PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

syntax:
	@$(PYTHON) -c 'import ast, pathlib; [ast.parse(path.read_text(), filename=str(path)) for path in pathlib.Path(".").rglob("*.py") if ".venv" not in path.parts]'

verify: static test syntax

# The acceptance gate for OK-95: fails while any distribution is still an
# assumption. `verify` reports the gap and stays green, so CI keeps running the
# static checks; this target is what "the capability delta is validated on both
# distributions" actually means.
verify-measured: $(DEPS_STAMP)
	@$(VENV_PYTHON) verify.py --require-measured

clean:
	@$(PYTHON) -c 'import pathlib, shutil; shutil.rmtree(pathlib.Path("$(VENV)"), ignore_errors=True)'
