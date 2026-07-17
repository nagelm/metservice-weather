#!/usr/bin/env bash
# Run ruff check + format in the WSL venv.
# Usage: wsl bash scripts/lint.sh [--fix]
set -e
VENV_DIR="${METSERVICE_VENV_DIR:-$HOME/.venv/metservice-weather}"
source "$VENV_DIR/bin/activate"
# Run from the repo/worktree this script lives in, not a hardcoded path.
cd "$(dirname "$(readlink -f "$0")")/.."
ruff check --fix .
ruff format .
