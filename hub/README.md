# forge-hub — hardened workshop for the AI ⇄ Godot chain

## Architecture (June 2026 hardening)

```
hub.py (FastAPI, 127.0.0.1:8003)
  thin HTTP + SSE; NO business logic
  │
  ├─ forge_env.py     parse/serialize stack.env ONCE, shared by hub + forge-model CLI
  ├─ forge_models.py  GGUF metadata, VRAM fit, registry, dry-run, apply plan
  └─ forge_ops.py     transactional swap with rollback, drift detection,
                       reconcile, failure classifier, durable action log
```

**Key design decisions:**

- **Single source of truth:** `forge_env.py` is the ONE parser for `stack.env`.
  Both `hub.py` and the `forge-model` CLI import it. No more drift (F7).

- **All mutating ops through `forge_ops.py`:** every action that touches the real
  system goes through one runner that records it to a durable JSONL log in
  `data/actions/` (F10) and knows how to roll back (F2).

- **The `forge-model` CLI is a thin wrapper** over `forge_models.py` — the same
  library the hub imports. The CLI and the hub can never diverge in behavior,
  and both are unit-testable without a server.

- **Transactional swap:** `swap_model()` snapshots `stack.env` before writing,
  polls `/health` with crash fast-fail (StartLimitBurst guards on the systemd
  unit — F3), verifies `/props` matches, and rolls back on ANY failure (F1, F2).

- **State reconciliation:** `check_drift()` compares configured vs running model
  on every status poll. The UI shows a red banner with a one-click reconcile
  button when they disagree (F3, F5).

- **Failure classifier:** `classify_failure()` maps known error signals
  (cudaMalloc OOM, segfault, port conflict, OOM killer) to plain-language
  cause + fix, surfaced in the Activity tab (F8).

## What it does

- Live status chips with **drift detection** (configured ≠ running → red banner)
- **Chain health sidebar** — always-on right panel with 8-link color-coded chain diagram,
  docker-internal reachability checks, MCP keyword detection, config-doc consistency
- Every `stack` command as a one-click button with live SSE output
- **Transactional model swap** with VRAM check, automatic rollback, ambiguity picker,
  phase-driven progress bar (VRAM check → restart → health poll → verification)
- **dry-run preview** (`forge-model plan` or Models tab hover)
- `stack.env` editor with schema validation, diff preview, timestamped backups
- Per-service log snapshots, the chain reference doc embedded
- **Activity tab** with durable action log and failure classifications
- **API version check**: stale tabs self-detect and prompt reload (F6)
- **Test Bench tab**: 21-layer chain tests + latest shootout summary with log link
- **Deep Probe** (in Bench tab): chain-ordered probes that emit structured **data**
  + a 3-tier verdict (works / degraded / broken) so you can tell "actually works"
  from "merely passes". 16 probes across llama → DevForge → godot-ai → runtime →
  Odysseus; CLI `python bench.py --probe`; runs persist to `data/bench/probe-*.json`.
  See `CHAIN-PROBES-DESIGN.md`.
- **Shootout tab** (Stream E): full model → Godot pipeline test with file-based logging, preflight check, scorecard history, inline log viewer
- **Score tab** (Stream A): scenario suite + tool-call probes + scorecard comparison
- **Models tab**: one-click swap with exact filename matching (no ambiguity)

## Design rules (do not erode)

- The `stack` CLI + stack.env stay the single source of truth — the hub
  shells out, it never reimplements stack logic
- Binds 127.0.0.1 only; Host-header allowlist + custom POST header
  (it executes systemctl/docker — must never be LAN-reachable)
- Whitelisted argv-list subprocesses only, one mutating job at a time
- Independent of forge-stack.target: `stack down` never kills the hub
- No Odysseus/godot-ai source patched

## Run

```sh
cd hub && .venv/bin/python hub.py    # or: systemctl --user start forge-hub
```

Tests: `cd hub && .venv/bin/python -m pytest tests/ -v`

## Files

| File | Purpose |
|------|---------|
| `hub.py` | FastAPI app, routes (`/api/chain-health`, `/api/models/search`, `/api/swap`, `/api/shootout/*`, etc.) |
| `forge_env.py` | stack.env parser/serializer/validator |
| `forge_models.py` | GGUF metadata, VRAM fit, registry, plan_apply, scan cache (2s TTL) |
| `forge_ops.py` | Transactional swap with reclaim, drift, reconcile, action log, failure classifier |
| `shootout.py` | Shootout runner: full apply_spec pipeline test + preflight check + file-based logging |
| `bench.py` | 21-layer chain test bench |
| `scenarios.py` | Scenario suite + tool-call probes for model scoring (Stream A) |
| `calibrate_vram.py` | Standalone VRAM calibration — loads each model × ctx, records peak VRAM |
| `static/index.html` | Vanilla JS UI: health sidebar, swap progress, ambiguity picker, scorecards |
| `tests/` | pytest — 121 unit + 11 live-integration tests |
| `data/actions/` | Durable JSONL action records (one file per day) |
| `data/shootouts/` | Shootout scorecards + companion `.log` files |
| `data/bench/` | Bench run history + saved bundles |
| `data/scorecards/` | Model scorecards from scenario suite runs |
