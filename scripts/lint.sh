#!/usr/bin/env bash
# Run ruff check + format in the WSL venv.
# Usage: wsl bash scripts/lint.sh [--fix]
set -e
source /home/user/.venv/metservice-weather/bin/activate
# Run from the repo/worktree this script lives in, not a hardcoded path.
cd "$(dirname "$(readlink -f "$0")")/.."
ruff check --fix .
ruff format .
