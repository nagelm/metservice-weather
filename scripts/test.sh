#!/usr/bin/env bash
# Run the test suite in the WSL venv.
# Usage: wsl bash scripts/test.sh [pytest args...]
# Example: wsl bash scripts/test.sh tests/test_coordinator_data.py -v
set -e
VENV_DIR="${METSERVICE_VENV_DIR:-$HOME/.venv/metservice-weather}"
source "$VENV_DIR/bin/activate"
# Run from the repo/worktree this script lives in, not a hardcoded path.
cd "$(dirname "$(readlink -f "$0")")/.."
exec pytest "${@:---q}"
