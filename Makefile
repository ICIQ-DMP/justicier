# Makefile for justicier
# Usage examples:
#   make venv
#   make lint
#   make fmt
#   make test
#   make run CMD="run -f demo.nds --debug"
#   make clean

SHELL := bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c


# ---- config ---------------------------------------------------------------

# Check if python3.14 exists, otherwise default to python
ifneq ($(shell command -v python3.14 2> /dev/null),)
    PYTHON_BIN ?= python3.14
else
	ifneq ($(shell command -v python3 2> /dev/null),)
    	PYTHON_BIN ?= python3
    else
    	PYTHON_BIN ?= python
    endif
endif

VENV_DIR     ?= venv
PKG_NAME     := justicier
DOCKER_IMAGE := AleixMT/justicier

# When CONTAINER=1 (set via ENV in Dockerfile) use system-wide tools;
# otherwise use the project venv. All targets below work in both contexts.
ifdef CONTAINER
    VENV_BIN      := /usr/local/bin
    PYTHON        := python
    PIP           := pip
    DEV_STAMP     := /tmp/.$(PKG_NAME)-dev-installed
    INSTALL_FLAGS :=
else
    VENV_BIN      := $(VENV_DIR)/bin
    PYTHON        := $(VENV_BIN)/python
    PIP           := $(VENV_BIN)/pip
    DEV_STAMP     := $(VENV_DIR)/.dev-installed
    INSTALL_FLAGS := -e
endif


# ---- environment (file targets) -------------------------------------------

# Create virtualenv
$(VENV_BIN)/python:
	@$(PYTHON_BIN) -m venv "$(VENV_DIR)"
	@$(PIP) install --upgrade pip

# Install runtime dependencies (creates justicier executable)
$(VENV_BIN)/justicier: $(VENV_BIN)/python pyproject.toml
	@$(PIP) install $(INSTALL_FLAGS) .

# Install dev dependencies
# We use a stamp file because pip may not update binary timestamps when a tool
# is already present, which would fool Make into skipping the install on the
# next run. Touching the stamp explicitly avoids that.
$(DEV_STAMP): $(VENV_BIN)/python pyproject.toml
	@$(PIP) install -e ".[dev]"
	@touch $(DEV_STAMP)

# Install git hooks (each hook is its own file target)
.git/hooks/pre-commit: $(DEV_STAMP)
	@$(VENV_BIN)/pre-commit install

.git/hooks/commit-msg: $(DEV_STAMP)
	@$(VENV_BIN)/pre-commit install --hook-type commit-msg

.git/hooks/pre-push: $(DEV_STAMP)
	@$(VENV_BIN)/pre-commit install --hook-type pre-push

# Install build tool
$(VENV_BIN)/pyproject-build: $(VENV_BIN)/python
	@$(PIP) install build


# ---- phony aliases --------------------------------------------------------

venv: $(VENV_BIN)/python  ## Create virtualenv

install: $(VENV_BIN)/justicier  ## Install package

hooks: .git/hooks/pre-commit .git/hooks/commit-msg .git/hooks/pre-push  ## Install git hooks

docs:  ## Init/update the docs submodule (justicier-docs)
	@git submodule update --init --recursive docs

dev: $(DEV_STAMP) hooks docs  ## Install dev dependencies, git hooks and docs submodule


# ---- quality --------------------------------------------------------------
# Depend on $(DEV_STAMP) directly (a real file) so Make can timestamp-check
# whether the environment is fresh without walking the full dev alias tree.
# The git hooks are intentionally excluded from this dependency chain.

lint: $(DEV_STAMP)  ## Run static checks (ruff + mypy)
	@$(VENV_BIN)/ruff check .
	@$(VENV_BIN)/mypy --strict src

fmt: $(DEV_STAMP)  ## Auto-format (black + ruff --fix)
	@$(VENV_BIN)/black src tests
	@$(VENV_BIN)/ruff check --fix .

test: $(DEV_STAMP)  ## Run tests
	@PYTHONUNBUFFERED=1 $(VENV_BIN)/pytest -s -v


# ---- run ------------------------------------------------------------------

# Pass arguments to the CLI via CMD, e.g.:
#   make run CMD="run -f demo.nds --debug"
CMD ?= --help
run: $(VENV_BIN)/justicier  ## Run the justicier CLI (python -m justicier)
	@$(PYTHON) -m $(PKG_NAME) $(CMD)


# ---- docker ---------------------------------------------------------------

docker-build:  ## Build the production Docker image
	@sudo docker build -t $(DOCKER_IMAGE) . --progress=plain

docker-build-dev:  ## Build the dev Docker image (used by docker-shell / docker-run)
	@docker build --target dev -t $(DOCKER_IMAGE):dev . --progress=plain

docker-push:  ## Push the Docker image
	@sudo docker push $(DOCKER_IMAGE)

docker-shell: docker-build-dev  ## Open a shell in a dev container with the project mounted
	@docker run --rm -it \
		-v "$(PWD):/app" \
		-w /app \
		$(DOCKER_IMAGE):dev \
		bash

docker-run: docker-build-dev  ## Run the justicier CLI in a dev container (use CMD= to pass args)
	@docker run --rm -it \
		-v "$(PWD):/app" \
		-w /app \
		$(DOCKER_IMAGE):dev \
		python -m justicier $(CMD)


# ---- maintenance ----------------------------------------------------------

clean:  ## Remove build/test artifacts
	@rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info "$(VENV_DIR)"


# ---- meta -----------------------------------------------------------------

.PHONY: venv install dev hooks docs lint fmt test run clean help dist docker-build docker-build-dev docker-push docker-shell docker-run

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .+$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
