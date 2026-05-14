#!/usr/bin/env bash
# sync_to_core.sh — copy integration source from the HACS repo into the ha-core branch.
#
# Usage:
#   bash scripts/sync_to_core.sh [--dry-run]
#
# The script rewrites the import prefix (custom_components → homeassistant.components)
# and patches manifest.json for Core requirements.  Core-only files (diagnostics.py,
# quality_scale.yaml) are preserved in ha-core and never overwritten by this script.
#
# Run from the root of the metservice-weather HACS repo.

set -euo pipefail

HACS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CORE_DIR="${CORE_DIR:-$HACS_DIR/../ha-core}"
SRC="$HACS_DIR/custom_components/metservice_weather"
DST="$CORE_DIR/homeassistant/components/metservice_weather"
TEST_SRC="$HACS_DIR/tests"
TEST_DST="$CORE_DIR/tests/components/metservice_weather"
DRY_RUN=false

# ── argument parsing ────────────────────────────────────────────────────────────
for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    --core-dir=*) CORE_DIR="${arg#*=}"; DST="$CORE_DIR/homeassistant/components/metservice_weather"; TEST_DST="$CORE_DIR/tests/components/metservice_weather" ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

# ── helpers ─────────────────────────────────────────────────────────────────────
log() { echo "[sync] $*"; }
run() { if $DRY_RUN; then echo "[dry-run] $*"; else "$@"; fi; }

if ! [ -d "$CORE_DIR" ]; then
  echo "ERROR: ha-core not found at $CORE_DIR" >&2
  echo "       Set CORE_DIR env var or pass --core-dir=/path/to/ha-core" >&2
  exit 1
fi

# ── files to copy (Core-only files are excluded from this list) ─────────────────
# diagnostics.py and quality_scale.yaml are maintained separately in Core.
INTEGRATION_FILES=(
  __init__.py
  config_flow.py
  const.py
  coordinator.py
  coordinator_types.py
  entity.py
  helpers.py
  icons.json
  manifest.json
  sensor.py
  strings.json
  weather.py
  weather_current_conditions_sensors.py
)

# ── sync integration source ─────────────────────────────────────────────────────
log "Syncing integration source → $DST"
for f in "${INTEGRATION_FILES[@]}"; do
  src_file="$SRC/$f"
  dst_file="$DST/$f"
  if ! [ -f "$src_file" ]; then
    log "  SKIP $f (not found in HACS repo)"
    continue
  fi

  # Rewrite import prefix for .py files
  if [[ $f == *.py ]]; then
    content=$(sed 's/custom_components\.metservice_weather/homeassistant.components.metservice_weather/g' "$src_file")
    if $DRY_RUN; then
      echo "[dry-run] would write $dst_file (import path rewritten)"
    else
      echo "$content" > "$dst_file"
      log "  copied $f (import paths rewritten)"
    fi
  else
    run cp "$src_file" "$dst_file"
    log "  copied $f"
  fi
done

# ── patch manifest.json for Core ────────────────────────────────────────────────
# Core manifest must not have "version"; URLs point to HA docs / core issue tracker.
log "Patching manifest.json for Core requirements"
MANIFEST="$DST/manifest.json"
if ! $DRY_RUN; then
  python3 - "$MANIFEST" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path) as f:
    m = json.load(f)
m.pop("version", None)
m["documentation"] = "https://www.home-assistant.io/integrations/metservice_weather"
m.pop("issue_tracker", None)
# quality_scale in Core is tracked separately from the HACS manifest.
# Set to "silver" (current declared tier); update manually when advancing.
m["quality_scale"] = "silver"
with open(path, "w") as f:
    json.dump(m, f, indent=2)
    f.write("\n")
PYEOF
  log "  manifest.json patched (version removed, URLs updated)"
else
  echo "[dry-run] would patch manifest.json (remove version, fix URLs)"
fi

# ── sync translations directory ─────────────────────────────────────────────────
TRANS_SRC="$SRC/translations"
TRANS_DST="$DST/translations"
if [ -d "$TRANS_SRC" ]; then
  log "Syncing translations/"
  run mkdir -p "$TRANS_DST"
  run cp -r "$TRANS_SRC/." "$TRANS_DST/"
  log "  translations synced"
fi

# ── sync tests ──────────────────────────────────────────────────────────────────
log "Syncing tests → $TEST_DST"
run mkdir -p "$TEST_DST"

# Copy test Python files (rewrite import prefix and remove custom-integration fixture)
for f in "$TEST_SRC"/*.py; do
  fname=$(basename "$f")
  dst_file="$TEST_DST/$fname"
  if $DRY_RUN; then
    echo "[dry-run] would write $dst_file (import paths rewritten)"
    continue
  fi
  sed 's/custom_components\.metservice_weather/homeassistant.components.metservice_weather/g' "$f" > "$dst_file"
  log "  copied tests/$fname (import paths rewritten)"
done

# Remove the custom-integration autouse fixture from conftest if present
CORE_CONFTEST="$TEST_DST/conftest.py"
if ! $DRY_RUN && [ -f "$CORE_CONFTEST" ]; then
  python3 - "$CORE_CONFTEST" <<'PYEOF'
import re, sys
path = sys.argv[1]
with open(path) as f:
    content = f.read()
# Remove the auto_enable_custom_integrations fixture block
content = re.sub(
    r'\n@pytest\.fixture\(autouse=True\)\ndef auto_enable_custom_integrations.*?yield\n',
    '\n',
    content,
    flags=re.DOTALL,
)
with open(path, "w") as f:
    f.write(content)
PYEOF
  log "  conftest.py: removed auto_enable_custom_integrations fixture"
fi

# Sync fixtures directory
FIXTURES_SRC="$TEST_SRC/fixtures"
FIXTURES_DST="$TEST_DST/fixtures"
if [ -d "$FIXTURES_SRC" ]; then
  run mkdir -p "$FIXTURES_DST"
  run cp -r "$FIXTURES_SRC/." "$FIXTURES_DST/"
  log "  fixtures synced"
fi

log ""
log "✓ Sync complete."
log ""
log "Core-only files NOT touched (manage these separately in ha-core):"
log "  homeassistant/components/metservice_weather/diagnostics.py"
log "  homeassistant/components/metservice_weather/quality_scale.yaml"
log "  CODEOWNERS"
log ""
if $DRY_RUN; then
  log "Dry-run mode — no files were changed."
fi
