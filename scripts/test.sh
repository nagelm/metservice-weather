#!/usr/bin/env bash
# Run the test suite in the WSL venv.
# Usage: wsl bash scripts/test.sh [pytest args...]
# Example: wsl bash scripts/test.sh tests/test_coordinator_data.py -v
set -e
source /home/mattn/.venv/metservice-weather/bin/activate
cd /mnt/c/Users/mattn/projects/metservice-weather
exec pytest "${@:---q}"
