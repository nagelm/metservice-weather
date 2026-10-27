#!/usr/bin/env bash
# Usage: wsl bash scripts/lint.sh [--fix]
set -e
VENV_DIR="${METSERVICE_VENV_DIR:-$HOME/.venv/metservice-weather}"
source "$VENV_DIR/bin/activate"
cd "$(dirname "$(readlink -f "$0")")/.."
ruff check --fix .
ruff format .
