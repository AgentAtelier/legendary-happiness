# Forge roadmap — toward AI that builds real Godot scenes

Two stages. **Stage 1 hardens everything that interacts with DevForge** (so we
can measure and iterate). **Stage 2 raises capability, smallest → biggest.**
Every Stage-2 phase is gated by the now-trustworthy benchmark from Stage 1.

Status legend: ✅ done · 🔨 in progress · ⬜ planned

---

## Stage 1 — Upgrade the interaction surfaces (do first)

### Phase 1 — Trustworthy benchmark harness  ✅ (completed June 13)
The benchmark is the instrument we'll use to judge every later change, and right
now it lies. Fixes (all in `hub/shootout.py` + a little UI):

- **Swap-alias resolution** ✅ — the shootout swapped using hardcoded aliases
  (`…-qat-ud-q4-k-xl`) that don't match `forge-model`'s derived aliases
  (`…-qat-q4-k-xl`), so 4/5 models failed to swap and were reported as `0/100`.
  Swap via the *resolved* model's real alias instead.
- **Untested ≠ scored-0** ✅ — a swap/plan failure now reports `untested`
  (excluded from rankings), not a fake 0.
- **FPS readiness** ✅ — poll `game_capture_ready` + FPS after launch (like the
  probe) instead of one early read that always returned 0.
- **Resilient runtime checks** ✅ — script assertions degrade gracefully when a
  script is missing/renamed (no raw "TaskGroup" errors), and match the model's
  actual script files instead of an exact hardcoded filename.

Exit criterion: a shootout where every model is genuinely tested and the score
reflects what was built (no swap-failure 0s, no false FPS fails).

### Phase 2 — Fast iteration + the two-model problem  ✅ (completed June 14)
- Busy banner + `/api/job/active` (non-blocking UI); one-click ⚒ Build / ✍ Write
  model toggle; <10s Quick Health (fast-probes bundle). Planner latency capped via
  `DEVFORGE_CONTEXT_TOKEN_BUDGET`. (Dual-serving ruled out — 16 GB can't hold two.)

### Phase 3 — Odysseus integration hardening  ✅ (completed June 14, config-only)
- MCP auto-reconnect on DevForge/godot-ai restart; persona check + "restore from
  vault"; embedding lane reported as FastEmbed (default, OK — Stage 1.1 F1);
  warmup is a documented manual one-chat step (chat API needs auth — Stage 1.1 F2).
  See `STAGE-1.1-FIXES.md`.

---

## Stage 2 — Capability (smallest → biggest)

### Phase 4 — Properties & resources  ✅ *(completed June 13–14)*
The structural ceiling: `apply_spec` builds node trees but sets no meshes,
shapes, materials, transforms, or text — so scenes are invisible/non-functional
(caps the shootout ~53). Extend the entity schema with optional:
`mesh` (Box/Sphere/Capsule/Plane), `shape` (collision), `material`/`color`,
`transform`/`position`, `text`, exported vars. Compiler emits `set_property` +
resource ops. **Target: ~70–80/100** (player/coin meshes, colliders, colors,
"Score: 0" all pass). Lower risk; keeps the current abstraction.

### Phase 5 — Real script behavior  ✅ *(completed June 14)*
Scripts today are stubs from one-line system descriptions. Generate *working*
GDScript (WASD movement, `body_entered` → `queue_free`, score tracking) from
`systems`/`connections`, validated by compile + the runtime probes. Unlocks the
32-point runtime half of the shootout.

### Phase 6 — Direct operation generation  ✅ *(completed June 14)*
Replace `systems/entities/connections` with the model emitting **operations
directly** (`add_node`, `set_property`, `create_script`, `attach_script`,
`connect_signal`) under a richer GBNF grammar, validated + executed. Removes the
lossy intermediate that Phases 4–5 keep patching; unlocks arbitrary detail in
one schema. Prototype behind a flag, A/B against the current path on the
benchmark before committing.

---

## Why this order
Stage 1 first because a benchmark that scores untested models 0 and real FPS as
dead can't guide anything. Then capability cheapest-first (4 → 5 → 6): Phase 4
buys the biggest visible jump for the least risk. Phase 6 is the high-ceiling
rewrite taken on once 4–5 prove where the abstraction breaks — and is gated
behind a flag with A/B comparison for safe rollout.

After capability work, a gruntwork audit hardened code quality (grammar sync,
shared resources, import hygiene) and diagnostics (pipeline telemetry, failure
attribution, regression detection, A/B planner comparison).
