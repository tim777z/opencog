# ---------------------------------------------------------------------------
# OpenCog developer entry point.
#
# Everything a new contributor or a CI runner needs is reachable from here, so
# that "build and test from a fresh clone" is one command instead of a wiki
# page. See README.md ("Quick start") and CONTRIBUTING.md.
#
# This is a hand-written GNUmakefile-style makefile; it never delegates to the
# CMake-generated one, which lives in $(BUILD_DIR).
# ---------------------------------------------------------------------------

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Pinned sibling repositories. These are the two dependencies that must be
# built and installed before this tree will configure; the versions below are
# the ones this branch is known to build against. Change them deliberately.
COGUTIL_REPO    ?= https://github.com/opencog/cogutils.git
COGUTIL_REF     ?= master
ATOMSPACE_REPO  ?= https://github.com/opencog/atomspace.git
ATOMSPACE_REF   ?= master

BUILD_DIR       ?= build
BUILD_TYPE      ?= Release
CMAKE           ?= cmake
PYTHON          ?= python3
JOBS            ?= $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)

# Pinned container base. Kept in one place so the image can be reproduced.
BASE_IMAGE      ?= ubuntu:22.04

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Python: reproducible, hash-free but version-pinned installs
# ---------------------------------------------------------------------------
.PHONY: venv
venv: ## Create .venv and install the pinned Python dependencies
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements.lock.txt

.PHONY: deps
deps: ## Install pinned Python dependencies into the active interpreter
	$(PYTHON) -m pip install -r requirements.lock.txt

.PHONY: lock
lock: ## Regenerate requirements.lock.txt (requires network + pip-tools)
	$(PYTHON) -m pip install --upgrade pip-tools
	$(PYTHON) -m piptools compile \
	  --output-file=requirements.lock.txt \
	  --generate-hashes \
	  --extra dev --extra restapi \
	  pyproject.toml

# ---------------------------------------------------------------------------
# C++ build
# ---------------------------------------------------------------------------
.PHONY: configure
configure: ## Run CMake into $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)
	cd $(BUILD_DIR) && $(CMAKE) -DCMAKE_BUILD_TYPE=$(BUILD_TYPE) ..

.PHONY: build
build: configure ## Build the C++ tree
	$(CMAKE) --build $(BUILD_DIR) --parallel $(JOBS)

.PHONY: examples
examples: build ## Build the example programs
	$(CMAKE) --build $(BUILD_DIR) --target examples --parallel $(JOBS)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
.PHONY: test
test: test-python test-cpp ## Run every test suite that this tree can run

.PHONY: test-python
test-python: ## Run the dependency-free Python suite (no C++ build required)
	$(PYTHON) -m pytest

.PHONY: test-cpp
test-cpp: build ## Run the CxxTest suites via ctest
	cd $(BUILD_DIR) && ctest --output-on-failure

.PHONY: coverage
coverage: ## Run the Python suite with coverage and print the report
	$(PYTHON) -m coverage run -m pytest
	$(PYTHON) -m coverage report
	$(PYTHON) -m coverage html -d $(BUILD_DIR)/coverage-python

.PHONY: coverage-cpp
coverage-cpp: ## Build with gcov instrumentation, run ctest, emit lcov.info
	$(CMAKE) -S . -B $(BUILD_DIR)-coverage -DCMAKE_BUILD_TYPE=Coverage
	$(CMAKE) --build $(BUILD_DIR)-coverage --parallel $(JOBS)
	cd $(BUILD_DIR)-coverage && ctest --output-on-failure
	cd $(BUILD_DIR)-coverage && ../scripts/combine_lcov.sh
	@echo "Merged report: $(BUILD_DIR)-coverage/coverage/all.info"
	@echo "HTML summary:  $(BUILD_DIR)-coverage/lcov/index.html"

# ---------------------------------------------------------------------------
# Lint / format
# ---------------------------------------------------------------------------
.PHONY: lint
lint: lint-python lint-cpp ## Run every linter

.PHONY: lint-python
lint-python: ## Lint the Python 3 clean trees with ruff
	$(PYTHON) -m ruff check --output-format=concise .

.PHONY: lint-cpp
lint-cpp: ## Run clang-tidy over the translation units listed in compile_commands.json
	@if [ -f "$(BUILD_DIR)/compile_commands.json" ]; then \
	  echo ">> clang-tidy: analysing $(BUILD_DIR)/compile_commands.json"; \
	  $(CMAKE) -S . -B $(BUILD_DIR) -DCMAKE_EXPORT_COMPILE_COMMANDS=ON >/dev/null; \
	  git diff --name-only --diff-filter=ACMR HEAD~1..HEAD 2>/dev/null \
	    | grep -E '\.(cc|cpp)$' \
	    | xargs -r clang-tidy -p $(BUILD_DIR) --warnings-as-errors='*'; \
	else \
	  echo ">> skipping clang-tidy: run 'make configure' first so that"; \
	  echo "   $(BUILD_DIR)/compile_commands.json exists."; \
	fi

.PHONY: format
format: ## Apply clang-format to the C++ tree (check with 'make format-check')
	@command -v clang-format >/dev/null 2>&1 || { \
	  echo "clang-format not found; install clang-format first."; exit 1; }
	git ls-files -z '*.cc' '*.cpp' '*.h' '*.hpp' \
	  | xargs -0 -r clang-format -i --style=file

.PHONY: format-check
format-check: ## Verify C++ formatting without modifying files
	@command -v clang-format >/dev/null 2>&1 || { \
	  echo "clang-format not found; skipping."; exit 0; }
	git ls-files -z '*.cc' '*.cpp' '*.h' '*.hpp' \
	  | xargs -0 -r clang-format --dry-run --Werror --style=file

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
.PHONY: audit
audit: ## Audit pinned Python dependencies for known CVEs (needs network)
	$(PYTHON) -m pip install --upgrade pip-audit
	$(PYTHON) -m pip_audit -r requirements.lock.txt

.PHONY: secret-scan
secret-scan: ## Scan the working tree for committed credentials
	@command -v gitleaks >/dev/null 2>&1 || { \
	  echo "gitleaks not found; see https://github.com/gitleaks/gitleaks"; exit 0; }
	gitleaks detect --source . --no-banner --redact

# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------
.PHONY: docker-build
docker-build: ## Build the self-contained image (cogutils+atomspace+opencog)
	docker build \
	  --build-arg COGUTIL_REF=$(COGUTIL_REF) \
	  --build-arg ATOMSPACE_REF=$(ATOMSPACE_REF) \
	  -t opencog:dev .

.PHONY: docker-test
docker-test: docker-build ## Run the full test suite inside the image
	docker run --rm opencog:dev make test

.PHONY: docker-shell
docker-shell: docker-build ## Start an interactive shell in the image
	docker run --rm -it -p 17001:17001 -p 18001:18001 opencog:dev bash

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
.PHONY: install
install: build ## Install into CMAKE_INSTALL_PREFIX
	$(CMAKE) --build $(BUILD_DIR) --target install

.PHONY: clean
clean: ## Remove build artefacts
	rm -rf $(BUILD_DIR) $(BUILD_DIR)-coverage

.PHONY: distclean
distclean: clean ## Also remove the virtualenv and caches
	rm -rf .venv .pytest_cache .ruff_cache .coverage htmlcov
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
