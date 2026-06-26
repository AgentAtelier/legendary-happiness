# Decision Points + Material Pre-Pass (Explainable, Recoverable Failure — Slice 1)

**Date:** 2026-06-19
**Branch:** `feat/foundry-decision-points` (off `feat/foundry-breadth-materials`)
**Premise:** qwen (small local model) is good enough — fixes are deterministic/architectural, never "use a bigger model / API." The LLM is a natural-language→parametric **compiler frontend**, not a creative engine.

## Why this slice

When the pipeline made a wrong/ambiguous decision (qwen picked `worn_oak` for a "wrought-iron cabinet"), it failed **opaquely** — the user got a wrong asset and no idea why or what to do. The thing that makes hobbyist gamedevs quit is opaque, unrecoverable failure. This slice introduces an **explainable, recoverable-failure layer** ("Decision Points") and proves it on its first real emitter — a **deterministic material pre-pass** that also fixes the material-selection bug.

This is **slice 1 of 3** (the other two are independent follow-ons, not in scope here): (2) LLM reliability tweaks — enum-order shuffle + few-shot; (3) multi-channel bake (roughness/normal).

## Design principles

- **Non-blocking:** the pipeline ALWAYS produces a result using its best guess. It never pauses to ask. It *emits* structured Decision Points the user can act on.
- **Dual-register, template-authored:** every Decision Point carries a `technical` and a `plain` message, from **hand-authored templates** with slots filled from context — deterministic and local, **never LLM-generated prose** (reliability + on-premise).
- **Data separated from presentation:** Decision Points are structured data carried in the result and persisted to the sidecar. A CLI renderer prints them now; the future UI reads the same data. No presentation logic inside the pipeline stages.
- **Material is removed from qwen's job entirely** — lexical material matching is a regex's task, not a model's.
- **Portable shape:** Decision Points land in `foundry/` but are designed to lift into the wider pipeline later. Do not over-build that now.

## Architecture

### The Decision Point (foundry/decisions.py — new)

```
SEVERITY = info | assumption | ambiguous | error   # string constants

@dataclass(frozen=True)
class Choice:
    label: str          # short ("Wrought iron")
    plain: str          # one-line non-technical description
    apply: dict         # concrete override, e.g. {"field": "material", "value": "wrought_iron"}

@dataclass(frozen=True)
class DecisionPoint:
    code: str           # "material.family_defaulted" | "material.unspecified_defaulted" | ...
    stage: str          # "planner" | "compiler" | "gate" | ...
    severity: str       # one of SEVERITY
    technical: str      # dev-facing message
    plain: str          # non-technical message
    context: dict       # {request, resolved, alternatives, ...}
    choices: list[Choice]
```

- A **template registry**: `code -> (technical_template, plain_template)`, formatted with `context`. A factory `make_decision(code, stage, severity, context, choices) -> DecisionPoint` fills both messages from the registry. Adding a new Decision Point type = one registry entry.
- `to_dict(dp) -> dict` for sidecar persistence.
- `render_cli(decisions) -> str`: human-readable dual-register block (plain line, then a dim technical line, then the numbered choices with their `apply`). Only this function knows about presentation.
- Only `assumption` / `ambiguous` / `error` are rendered by default; `info` is carried but quiet.

### The material pre-pass (foundry/material_resolver.py — new)

`resolve_material(request: str) -> tuple[str, list[DecisionPoint]]`, deterministic, runs **before** qwen.

- Build the keyword maps from `MATERIAL_PALETTE` (group entries by their `family` field — no hard-coded material list duplicated).
- **Specific-material keywords** (most specific wins): `oak→worn_oak`, `walnut→dark_walnut`, `pine→weathered_pine`, `granite/marble→rough_granite`, `iron/wrought/steel→wrought_iron`.
- **Family keywords:** `wood/wooden/timber→family "wood"`, `stone/rock→family "stone"`, `metal/metallic→family "metal"`.
- Resolution outcomes:
  - **Confident** — a specific keyword matched, OR a family keyword matched a family with exactly ONE member (stone→rough_granite, metal→wrought_iron): return that material, **no Decision Point**.
  - **Family-only with multiple members** — e.g. "wooden" (wood has 3): return the family default (`worn_oak`), emit `material.family_defaulted` (severity `assumption`) whose choices are the *other* members of that family.
  - **No match** — return `worn_oak`, emit `material.unspecified_defaulted` (severity `assumption`) whose choices are *all* materials.
- A deterministic per-family default (e.g. first-declared member). `worn_oak` is the global fallback.

### Wiring (foundry/planner.py, grammar, runner.py, sidecar.py, __main__.py)

- **planner.py:** `plan()` calls `resolve_material(request)` first, sets `spec["material"]` from it, and collects the returned Decision Points. **Material is removed from the LLM's responsibility:** delete the material lines from the prompt and stop asking qwen for it; remove the now-dead material-clamp fallback. The planner returns the spec plus its decisions (e.g. `plan()` returns the spec and exposes decisions, or returns a small result object — implementer's call, but decisions must reach the caller).
- **grammar/asset_spec.gbnf:** remove the `"material"` field from the `root` rule (single-line edit). qwen now emits asset_id, generator, age, params only.
- **runner.py:** `ForgeResult` gains `decisions: list[DecisionPoint]`. Both `forge()` (explicit spec — material given, so usually empty) and `forge_from_request()` (planner path — carries the resolver's decisions) populate it.
- **sidecar.py:** persist `decisions` (via `to_dict`) into the sidecar JSON so the future UI reads the same events.
- **__main__.py:** after a `--request` forge, print `render_cli(result.decisions)`.

## Tests

- **resolver:** "oak table"→`worn_oak`, no decision; "wooden table"→`worn_oak` + one `material.family_defaulted` whose choices are walnut+pine; "wrought-iron cabinet"→`wrought_iron`, no decision (the headline bug — assert it's fixed); "granite shelf"→`rough_granite`, no decision; "a nice table" (no material word)→`worn_oak` + `material.unspecified_defaulted` with all materials as choices.
- **decisions:** `make_decision` fills both registers from templates; `to_dict` round-trips; `render_cli` shows plain + technical + numbered choices; `info` is not rendered.
- **planner:** with a FAKE llm whose JSON has NO material field (grammar no longer requires it), `plan()` still yields a valid spec whose material came from the resolver, and the decisions are reachable.
- **grammar:** the root rule no longer contains `"material"`; a planned spec still passes `compile_spec`.
- **integration / regression:** `forge_from_request` end-to-end attaches decisions and writes them into the sidecar; existing forge tests still green.

## Out of scope (this slice)

Programmatic one-click re-resolve (choices are concrete overrides the user applies by re-forging — the click belongs to the UI later); a beginner "hand-holding" renderer; blocking/interactive mode; lifting Decision Points into the wider devforge pipeline; the reliability tweaks and multi-channel bake (slices 2 and 3).
