#!/usr/bin/env bash
# Run the test suite in the WSL venv.
# Usage: wsl bash scripts/test.sh [pytest args...]
# Example: wsl bash scripts/test.sh tests/test_coordinator_data.py -v
set -e
source /home/user/.venv/metservice-weather/bin/activate
# Run from the repo/worktree this script lives in, not a hardcoded path.
cd "$(dirname "$(readlink -f "$0")")/.."
exec pytest "${@:---q}"
