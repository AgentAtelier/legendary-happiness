# forge-hub Hardening Roadmap

**Audience:** an implementing AI (or human) tasked with making forge-hub a
dependable tool instead of a time sink.
**Author:** prior session, June 13 2026, after the hub's model-swap path
silently bricked the chain.
**Mandate from the owner:** *"Revisit every part of it and make it solid and
more easy to track what went wrong. I'm happy with what I can see, but under
the hood it's too brittle to use."*

---

## 0. Philosophy (read first, do not skip)

The hub is the **workshop** — the thing you reach for *when something is
already broken*. That means it must be the single most reliable, most
observable component in the whole system. Today it is the opposite: it
inherits every fragility of the scripts it wraps and adds its own, and when it
fails it fails **silently** (a hung stream, an "undefined", a swap that never
completes). A workshop tool that you can't trust when things are on fire is
worse than no tool.

Three non-negotiable properties to design toward:

1. **Fail fast, fail loud, fail safe.** Every operation that can't succeed must
   stop quickly, say *why* in plain language, and leave the system in the state
   it was in before (rollback). No hangs. No half-applied config.
2. **Always answer "what just went wrong?"** Every action produces a durable,
   inspectable record: the exact command, its output, exit status, timing, and
   — on failure — the root-cause signal (e.g. the llama OOM line), surfaced in
   the UI, not buried in journalctl.
3. **One source of truth, no drift.** `stack.env` is the configuration truth;
   the *running* system is the runtime truth; the hub must continuously
   reconcile the two and show the user when they disagree.

### Hard constraints (carry forward — violating these is a regression)

- **Do not fork Odysseus or godot-ai.** Adapt our own code (hub, forge-model,
  stack, DevForge) or use supported config. See `upstream-fork-policy` memory.
- **`stack.env` + the `stack`/`forge-model` CLIs stay the single source of
  truth.** The hub shells out to them; it must never grow a parallel
  implementation of swap/start/stop logic.
- **Loopback only.** The hub executes `systemctl`/`docker`; it must never bind
  beyond `127.0.0.1`, and must keep the Host-allowlist + CSRF-header guards.
- **Independent of `forge-stack.target`.** `stack down` must never kill the hub.

---

## 1. Catalog of observed failure modes (the evidence base)

These are real, reproduced this engagement. Each item below is a thing the
hardened hub must *prevent, detect, or explain*. Use this as the regression
checklist — every one needs a test.

| # | Failure | Root cause | Today's symptom |
|---|---------|-----------|-----------------|
| F1 | **Swap to a too-big model bricks llama** | VRAM fit estimate is optimistic (`forge-model.fit()` undercounts real allocation). 26B @ ctx 32768 reported "tight, fits 15.0/16.0G" but `cudaMalloc failed: out of memory` → core-dump | `stack model` waits 180s for `/health` that never comes; hub stream hangs; user sees nothing actionable |
| F2 | **No rollback on failed swap** | Apply mutates `stack.env` first, restarts after; if the restart fails the config is already changed | Chain left pointing at a model that won't load; `systemd Restart=on-failure` crash-loops it |
| F3 | **Crash-loop "recovers" into a different model** | systemd restarts llama; if `stack.env` MODEL was changed meanwhile, it silently loads a *different* model than the user chose | Running model ≠ configured model ≠ what the user asked for; no signal |
| F4 | **`forge-model apply` has no dry-run** | `apply` writes `stack.env` immediately; there is no "preview what this swap would do" | Merely *testing* a swap mutates real config |
| F5 | **Config-vs-running desync is invisible** | `forge-model list`'s ● comes from `stack.env`; the actually-loaded model can differ | The list lies about what's running |
| F6 | **Stale hub page → "undefined"** | Frontend JS and backend API field names drift; an open tab runs old JS against new API | Model sizes/fields render `undefined`; looks broken |
| F7 | **Env parsing is duplicated and naive** | `hub._read_env` and `forge-model.read_env` are two copies; both do `.strip('"')` which mishandles single-quoted values (the new `LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{...}'`) | Latent: a quoted value parses wrong in one place but not the other |
| F8 | **Failures require a human to read journalctl** | The hub surfaces command stdout but not the *diagnostic* (the OOM line lives in `journalctl -u forge-llama`, not in `stack model` output) | Every failure becomes "ask the operator/AI to dig" |
| F9 | **No tests for hub/forge-model logic** | The bench tests the *chain*; the hub's own fit math, env parsing, swap orchestration, and endpoints have zero coverage | Regressions ship silently (this roadmap exists because of one) |
| F10 | **In-memory job state, no history** | `_jobs` dict is lost on hub restart; no record of "what did I run and what happened" | Can't review past actions; the thing the owner explicitly wants ("track what went wrong") is absent |

---

## 2. Target architecture

```
                    ┌─────────────────────────────────────┐
                    │  hub.py  (FastAPI, 127.0.0.1:8003)   │
                    │  thin HTTP + SSE; NO business logic  │
                    └───────────────┬─────────────────────┘
                                    │ imports
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
  forge_env.py               forge_models.py              forge_ops.py
  (parse/serialize           (GGUF metadata, VRAM         (whitelisted command
   stack.env ONCE,            fit, registry, dry-run       runner, job records,
   shared by hub +            preview, apply plan)         rollback, log capture)
   forge-model CLI)                                         │
        │                                                   ▼
        └───────── single source of truth ───────►  jobs/  (durable JSONL
                       stack.env                      one record per action)
```

Key moves:

- **Extract a shared library** (`forge_env.py`, `forge_models.py`) used by BOTH
  `hub.py` and the `forge-model` CLI. One parser, one fit estimator, one
  registry. No more drift (kills F7, halves F5).
- **The `forge-model` CLI becomes a thin wrapper** over the same library the
  hub imports — so the CLI and the hub can never diverge in behavior, and both
  are unit-testable without a server.
- **All mutating ops go through one runner** (`forge_ops.py`) that records every
  action to a durable log and knows how to roll back.

---

## 3. Phased plan

Each phase is independently shippable and leaves the hub working. Do them in
order; later phases assume earlier ones. **After every phase: run the hub's own
test suite (Phase 1 builds it) and the chain bench.**

### Phase 1 — Make it testable (foundation; do this first)

Without tests, every later change is a new F9. Build the harness first.

1. Extract `forge_env.py`: `read_env(path) -> dict`, `write_env(path, updates)`,
   correct quote handling (single AND double, JSON values with spaces). Make
   `hub.py` and `forge-model` both import it. Delete the two copies.
2. Extract `forge_models.py`: GGUF parse, `detect()`, `fit()`, registry
   load/save, **and a new `plan_apply(fragment) -> ApplyPlan`** that returns
   what *would* change without writing anything (dry-run, fixes F4).
3. Add `hub/tests/` with `pytest`:
   - `test_forge_env.py`: round-trip parse/serialize, the single-quoted JSON
     value, comments, blank lines, values containing `=`.
   - `test_forge_models.py`: fit math on synthetic GGUF headers; alias
     uniqueness/collision; template mapping; override application.
   - `test_hub_api.py`: FastAPI `TestClient` — every endpoint, the Host/CSRF
     guards (403 paths), the job lifecycle, the 409-when-busy.
- **Acceptance:** `pytest hub/tests/` green; `forge-model` and the hub produce
  byte-identical `stack.env` writes for the same swap (golden test).

### Phase 2 — Trustworthy model swaps (fixes F1, F2, F3, F4)

The swap path is the #1 source of pain. Make it bulletproof.

1. **Pre-flight VRAM check before writing anything.** Query *free* VRAM at swap
   time (not total) from `/sys/.../mem_info_vram_used` vs `_total`, or
   `rocm-smi`. Recompute fit conservatively (the current estimate OOMed at a
   reported "15.0/16.0" — raise `RESERVE`, stop trusting the SWA `*0.45` fudge,
   add a measured safety margin). If it won't fit, **refuse the swap with a
   clear message and a suggested ctx** — never write config that can't load.
2. **Apply as a transaction:** snapshot the current `stack.env` LLM block →
   write new → restart llama → wait for `/health` AND verify `/props`
   `model_path` matches the requested file. On ANY failure (timeout, crash,
   wrong model loaded), **roll back to the snapshot, restart, and report the
   captured failure reason** (Phase 4 gives you the reason capture).
3. **Break the crash-loop:** while a swap transaction is in flight, treat a
   llama core-dump as a hard failure immediately (watch `systemctl is-failed`
   / `ExecMainStatus`), don't wait the full 180s. Consider
   `StartLimitIntervalSec`/`StartLimitBurst` on `forge-llama.service` so a
   genuinely bad config stops crash-looping and lands in `failed` with a clear
   state.
4. **Dry-run in the UI:** the Models tab shows the `plan_apply` result on hover
   / before confirm ("will set ctx 16384, template gemma, restart llama +
   devforge, est. 12.8/16.0 GB").
- **Acceptance:** swapping to a model that cannot fit FAILS in <5s with a
  message naming the reason and a working suggestion, and leaves the previously
  loaded model running. Reproduce F1 (26B @ 32k) and confirm it's now a clean
  refusal, not a brick.

### Phase 3 — State reconciliation (fixes F3, F5)

1. A single `status()` that reports BOTH configured (`stack.env`) and running
   (`/props model_path`, `systemctl is-active/is-failed`) state, and a
   **`drift` flag** when they disagree, with the reason.
2. The hub header and Models tab show drift prominently ("configured: X,
   running: Y — click to reconcile").
3. `stack`/hub gain a `reconcile` action: restart the service to match config,
   or offer to adopt the running state.
- **Acceptance:** induce drift (change MODEL without restart) → the hub shows it
  within one refresh and offers a one-click fix.

### Phase 4 — Observability: "what just went wrong?" (fixes F8, F10)

This is the heart of the owner's request.

1. **Durable action log:** every mutating op appends a JSONL record to
   `hub/data/actions/` — timestamp, action, argv, exit code, duration, full
   output, and (on failure) the **diagnostic tail** harvested from the relevant
   service journal (`journalctl --user -u forge-<svc> --since <start>` filtered
   to error lines). One record per action; never lost on restart.
2. **Failure reason extraction:** a small classifier maps known signals to
   plain-language causes + fixes: `cudaMalloc.*out of memory` → "Model too big
   for VRAM at this context — lower ctx or pick a smaller model"; `failed to
   parse grammar` → grammar issue; `address already in use` → port conflict;
   etc. Surface this, not the raw trace.
3. **UI:** an "Activity" tab (or panel) listing recent actions with status and
   one-click expand to the full record + extracted reason. This is what the
   owner means by "easy to track what went wrong."
- **Acceptance:** every failure in the F-table renders a human-readable cause +
  suggested fix in the UI, sourced from the durable log, with zero manual
  journalctl.

### Phase 5 — Frontend robustness (fixes F6)

1. Version the API: hub serves a build id; the page checks it and self-reloads
   (or shows "reload me") on mismatch. Keep the `no-cache` header.
2. Defensive rendering: never interpolate a possibly-undefined field; show
   explicit "—"/"unknown" and log a console warning naming the missing field.
3. A tiny `/api/selfcheck` the page calls on load: confirms the JS's expected
   API shape matches the server; renders a clear banner if not.
- **Acceptance:** loading an intentionally-stale page shows a reload prompt, not
  "undefined"; a renamed API field surfaces a named warning, not silent blanks.

### Phase 6 — Polish & guardrails

1. Replace ad-hoc validation (the `"LLAMA_BIN" in text` config-save check) with
   a real `stack.env` schema validator (required keys, types, the safety-cap
   invariant `--n-predict` present) run before any save, with a diff preview.
2. Config save: show a diff and keep the existing timestamped backups; add a
   one-click "restore last backup".
3. Document the hub's own architecture in `hub/README.md` (the library split,
   the action log, the swap transaction) so the next maintainer doesn't
   re-learn it from incidents.

---

## 4. Test & acceptance strategy (cross-cutting)

- **Unit:** `forge_env`, `forge_models` (fit/alias/template/plan), failure
  classifier — pure functions, synthetic GGUF headers, no live services.
- **API:** FastAPI `TestClient` for every endpoint + guards + job lifecycle.
- **Integration (live, opt-in):** the existing chain bench already covers the
  chain; add hub-level integration tests that drive a real swap to a
  known-fitting model and a known-too-big model, asserting success and clean
  refusal+rollback respectively.
- **The regression bar:** every row in §1's F-table has a test that would have
  caught it. A phase isn't done until its F-rows are red-then-green.

---

## 5. Definition of done

- Swapping to any model in `~/models` either succeeds and is verified loaded, or
  fails in seconds with a plain-language reason and the previous model still
  running. **No hang, no brick, no crash-loop.**
- Every action is recorded and every failure is explained in the UI without
  touching a terminal.
- `stack.env` parsing/serialization, fit estimation, and swap orchestration each
  have unit tests; the hub has API tests; both run in CI-style `pytest hub/tests`.
- Configured-vs-running drift is always visible and one-click reconcilable.
- `forge-model` CLI and the hub share one library and cannot diverge.
- No new binds beyond loopback; guards intact; `stack down` still never kills the
  hub; no Odysseus/godot-ai source patched.

---

## 6. Pointers (current code, for the implementer)

- `hub/hub.py` — FastAPI app; `_read_env` (dup #1), `/api/run` job model,
  `_job_runner`, `/api/models` (shells `forge-model list --json`).
- `hub/bench.py` — the chain test bench (21+ tests); good prior art for the
  failure-classifier style (each test returns a plain-language reason).
- `~/dotfiles/forge-stack/.local/bin/forge-model` — `read_env` (dup #2),
  `detect()`, `fit()` (the OPTIMISTIC estimator — F1), `cmd_apply` (no dry-run),
  registry in `~/.config/forge-stack/models.json`.
- `~/dotfiles/forge-stack/.local/bin/stack` — `cmd_model` (wraps forge-model +
  service restarts + the `wait_for /health` that hangs on a bad model — F1/F2).
- `~/dotfiles/forge-stack/.config/systemd/user/forge-llama.service` —
  `Restart=on-failure` (the crash-loop — F3); add start-limit guards here.
- `stack.env` — single source of truth; note the single-quoted
  `LLAMA_ARG_CHAT_TEMPLATE_KWARGS` value that the naive `.strip('"')` mishandles.
- Everything is stowed from `~/dotfiles/forge-stack` (GNU stow); edit there, not
  the `~/.config` / `~/.local` symlinks.

---

## 7. Explicitly out of scope (don't gold-plate)

- Multi-user / auth — single local operator only.
- Remote access — loopback forever.
- Reimplementing model download / serving — models are dropped into `~/models`
  by hand, by design.
- The dedicated **test-bench expansion** (scenario suites, per-model scorecards)
  is a *separate* future track — keep this roadmap to making the existing hub
  solid.
