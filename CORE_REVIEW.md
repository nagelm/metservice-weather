# metservice_weather — HA Core Submission Status

**Last updated:** 2026-05-14 · **Current HACS version:** v1.0.1

## Status: Core branch ready — awaiting brands + docs PRs

The integration is IQS Silver-compliant and has a live Core branch at
`nagelm/core:add-metservice-nz-weather`. All code-level requirements are met.
The remaining steps are procedural (brands repo, documentation page, opening the PR).

---

## What's done

| Area | Status |
|------|--------|
| Public API only (no private key) | ✅ |
| `manifest.json` — no `version`, correct fields | ✅ handled by `sync_to_core.sh` |
| `asyncio.timeout` throughout | ✅ |
| Translation keys + `strings.json`/`en.json` | ✅ |
| `icons.json` + icon-translations | ✅ |
| `diagnostics.py` | ✅ |
| `quality_scale.yaml` — IQS Silver declared | ✅ |
| `MetServiceEntity` base class + DeviceInfo | ✅ |
| `suggested_display_precision` on all numeric sensors | ✅ |
| `MetServiceConfigEntry` type alias | ✅ |
| Stable unique IDs | ✅ |
| `async_get_clientsession` throughout | ✅ |
| `from __future__ import annotations` everywhere | ✅ |
| Reconfigure support | ✅ |
| 206 tests, 95.8% coverage | ✅ |
| hassfest passes | ✅ (known flag: `brands: todo`) |
| `CODEOWNERS` entry | ✅ |

---

## Remaining submission steps

### 1. Brands PR → `home-assistant/brands`
- Create `core/metservice_weather/` directory in the brands repo
- Add `icon.png` — 256×256 transparent PNG, icon only (no wordmark)
- Optionally add `logo.png` (full wordmark) and `icon@2x.png` (512×512)
- See the [brands repo README](https://github.com/home-assistant/brands) for exact specs
- After merge: update `quality_scale.yaml` `brands: todo → done`, run `bash scripts/sync_to_core.sh`

### 2. Documentation page → `home-assistant/home-assistant.io`
- File: `source/_integrations/metservice_weather.markdown`
- Content drawn from README; required sections per IQS docs rules:
  - High-level description (what MetService is, what the integration provides)
  - Installation instructions (HACS path no longer applies — just Settings → Integrations)
  - Configuration (two-screen setup, marine options)
  - Supported functions (sensor list, weather entity)
  - Use cases
  - Known limitations (NZ only; 20-min polling; no GPS locations)
  - Troubleshooting
  - Data update frequency
  - Examples (automation snippets)
- Submit this PR alongside the Core integration PR; link both to each other

### 3. Update `quality_scale.yaml` + sync
After brands PR merges and docs PR is submitted:
```bash
# in the HACS repo:
bash scripts/sync_to_core.sh
# then in ha-core:
# edit quality_scale.yaml: brands → done, docs-* → done
# commit + push
```

### 4. Open the Core integration PR
- From: `nagelm/core:add-metservice-nz-weather`
- To: `home-assistant/core:dev`
- PR description must include:
  - Short summary (what MetService is, what the integration provides)
  - Checklist confirming test coverage, hassfest, mypy
  - Link to brands PR (should be merged by now)
  - Link to docs PR (may still be open — that's normal)
- Add label: `new-integration`
- Expect 2–8 week review cycle

### 5. During review
- Use `bash scripts/sync_to_core.sh` to propagate any HACS bug fixes to the branch
- Backport reviewer-requested changes to HACS repo manually
- Core reviewers may request: stricter typing, additional test cases, docstrings, refactoring

### 6. Post-acceptance (Phase 4)
- Extract `pymetservice-nz` PyPI library — Platinum IQS requirement (`async-dependency`)
- Once in Core, HACS version becomes a thin compatibility shim for users on older HA versions

---

## Sync workflow (ongoing)

```bash
# After any change to the HACS repo that should go to Core:
bash scripts/sync_to_core.sh        # rewrites paths, patches manifest
cd ../ha-core
git add -A && git commit -m "Sync from HACS repo"
git push
```

Core-only files **never** overwritten by the sync script:
- `homeassistant/components/metservice_weather/diagnostics.py`
- `homeassistant/components/metservice_weather/quality_scale.yaml`
- `CODEOWNERS`
