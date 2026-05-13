#!/usr/bin/env bash
# Run ruff check + format in the WSL venv.
# Usage: wsl bash scripts/lint.sh [--fix]
set -e
source /home/user/.venv/metservice-weather/bin/activate
cd /mnt/c/Users/user/projects/metservice-weather
ruff check --fix .
ruff format .
