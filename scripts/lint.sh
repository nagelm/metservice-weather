#!/usr/bin/env bash
# Run ruff check + format in the WSL venv.
# Usage: wsl bash scripts/lint.sh [--fix]
set -e
source /home/mattn/.venv/metservice-weather/bin/activate
cd /mnt/c/Users/mattn/projects/metservice-weather
ruff check --fix .
ruff format .
