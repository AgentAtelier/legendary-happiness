# ACCEPTED — Won't-Fix Register

_Phase 0.9. Solves [AUDIT-03 Q19](../current/AUDIT-03-quality.md) rudiment: the project has lint
findings that we have **consciously chosen NOT to fix**, either because they fight ruff/B-ignore
overrides, or because the "fix" would be a fight-not-worth-it against tightly scoped math helpers,
or because they require a different phase of work to address properly._

This doc is **noise prevention, not noise reduction**: it lets the next audit round skip these
findings without losing them. A finding listed here is *not* dismissed from the codebase — it
remains observable in source. Just don't spend cycles re-flagging it.

---

## Foundry · `pyproject.toml` ruff-disabled rule IDs

These rules **are flagged in source** but the project has elected to ignore at the linter level.
Rationale: a previous audit already weighed the value of every rule; the project keeps the ruler
opinion rather than the noise.

| Rule                                | Audit citation                            | Why we leave it ignored                                                                                                              |
|-------------------------------------|-------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| `B904` — `raise ... from` required  | `AUDIT-03 Q11`                            | Hub/server has ~25 `except Exception as e:` sites that re-raise. Adding `from e` to every re-raise is busywork; the message text is preserved. |
| `B028` — `stacklevel=` on warnings  | (none, ad-hoc)                            | We use `warnings.warn(...)` in tightly scoped helpers. Changing all sites to compute call frame is more noise than the gain. |
| `B007` — unused-loop-control variable | (none)                                   | Stable ignore; whitelist this for `for _ in [...]` patterns where the `_` is intentional.                                            |
| `B011` — `assert False` "can't happen" | (none, intentional)                     | We intentionally use `assert False, "...# pragma: no cover"` style markers in deterministic validators — see e.g. `gate.py`. |
| `B023` — function uses loop variable | `AUDIT-03 (subjective, intentional)`    | Closed-over loop variables are a real pattern in `brief.py` / `scene_compiler.py`'s callbacks. We accept these. |
| `B905` — `zip()` without `strict=` | (none; deferred)                          | Projects on 3.10-incompat — `strict=True` adds a `ValueError` site we don't want for batches that are guaranteed equal length. |
| `F841` — unused local var           | (none, noisy on AI code)                 | AI-written and review-mode patches commonly introduce intermediate variables during refactor. Keep flagging but don't auto-remove. |
| ~~`UP006` / `UP007` / `UP024`~~         | ~~`AUDIT-03 Q12` / `Q16`~~                    | ~~**PEP-604 modernization** is a separate phase of work — touching it in this turn risks story rotation across the ~30 files mixing `Dict`/`dict` and `Optional[X]`/`X \| None`. Phase 1.4 (decompose `scene_compiler.py`) is the right time. Cited from `AUDIT-03 Q12` and `Q16`.~~ DONE in `8d6aa60` — also: `UP006`/`UP007`/`UP024` were **removed** from `[tool.ruff.lint] ignore` in `pyproject.toml`; the rules are now LIVE. |

---

## Foundry · taste-level findings we're NOT touching now

| Audit citation (id + where)                            | What it says                                                              | Why we accept it                                                                                                                                  |
|--------------------------------------------------------|---------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| ~~`AUDIT-03 Q9` — duplicate ≥`npc_count` carryables enforcement~~ | ~~Both `layout_room` AND `plan_multi` enforce ≥ distinct carryables.~~       | ~~Two layers, but they apply different recovery strategies. Demoting `plan_multi`'s raise to a Decision Point is the fix; the duplication is currently safer.~~ ✓ done in `6759550` |
| `AUDIT-03 Q11` — `except Exception` swarm              | Hub/error paths often `except Exception as e: continue/sleep/retry`.       | A central `ForgeError` taxonomy is the right fix; Phase 1.5 work. Acknowledging the swamp is better than a half-fix that lands churn.            |
| ~~`AUDIT-03 Q13` — `_fmt_pos` vs inline `f"{}"`~~          | ~~Two formatting conventions coexist in `scene_compiler.py` emit blocks.~~    | ~~Phase 1.4 (decompose scene_compiler) — separate emit module gets the convention for free.~~ ✓ done in `1be7e06` |
| ~~`AUDIT-03 Q14` — single-letter locals `ox/oz/px/pz/hx/hz` in `_find_open_npc_positions`~~ | ~~Tight math helpers, 7 distractor variables.~~ | ~~Reading-cost > bughunt benefit. Renaming during Phase 1.4.~~ ✓ done in `d3e814e`                                                                                       |
| ~~`AUDIT-03 Q15` — stale `compile_scene` docstring~~        | ~~Docstring trails reality (missing `lighting_plan`, `palette`, `CB-7` branch).~~ | ~~Docstring refresh rides Phase 1.4.~~ ✓ done in `da1706f`                                                                                                               |
| ~~`AUDIT-03 Q16` — redundant `from typing import … Optional`~~ | ~~Optional/List/Dict imported despite zero usage.~~                          | ~~Same Phase 1.4 as `Q12`. Plenty of `Optional` usage but in some files it's truly dead; the project-wide sweep is its own chore.~~ ✓ done in `8d6aa60`                  |
| ~~`AUDIT-03 Q17` — `FIX-1` docstring lies about scope~~     | ~~After CB-4 the docstring is wrong; no Decision Point on NPC-push.~~         | ~~Decision Point emission in `_resolve_prop_overlaps` pair-tasks with the Phase 1.4 decompose.~~ ✓ done in `af93576`                                                       |
| `CODE-AUDIT X7` — `random.Random(42)` in `room_layout.py:110` | Spread-shuffle uses fixed seed; not caller-configurable.              | `room_layout.py` is fixed-point for the foreseeable future — the spread is bounded. Phase 0.8 (`_constants.py`) makes the seed visible at usage site but doesn't make it caller-configurable. |
| ~~`CODE-AUDIT X8` — `sys.exit(main())` in `__main__.py`~~  | ~~Importing `foundry.__main__` runs the CLI.~~                                | ~~The pattern is intentional for `python -m foundry xxx`; ad-hoc importers use `subprocess` instead. Worth a `__name__ == "__main__"` guard but pragmatic.~~ DONE in `af93576` |
| `CODE-AUDIT X9` — empty `__init__.py` / `conftest.py`   | Placeholder files give a false "registered" impression.                  | Empty-but-present is the standard Python convention; we add content if and when a useful re-export / fixture arises.                            |
| ~~`CODE-AUDIT X12` — module-level `main()` in `blender/render_asset.py` + 2 sister files~~ | ~~Importing these files triggers `bpy` side-effects.~~ | ~~Blender scripts run in dedicated subprocess via `runner.forge`; protected routes skip the import. Phase 1 work to add `__name__ == "__main__"` guards.~~ ✓ done in `af93576` |
| `WS5-CODE-REVIEW r7 #3` — `gate.py` degenerate-threshold over-penalizes thin props | Hardcoded `value < 0.01` flag for thin geometry. | A heuristic rug-vs-coin split is intentional; configurable threshold is a Phase 2.x perf chore.                                                |
| `WS5-CODE-REVIEW r9 #5` — dialogue validator `_validate_npc_role` doesn't catch `"hermit"` vs `"hermits"` | Adjacent-duplicate detection misses tense. | Prefix-stem match would be an over-fit (catches more false positives). Decision Point severity already lets the operator see the issue. Phase 1.4. |

---

## How to USE this doc

- When a future audit surfaces a finding like "ruff: 3 × `B904` violations remaining", do **not** re-flag it as "won't-fix in this commit" — instead, cite this doc.
- When a finding here is later addressed, **strike the row through** (use `~~` markdown) and add a brief commit-ref footnote. Don't delete history.
- New ACCEPTED entries must be added before the work that creates them lands, not after — that way the next audit round knows "the previous team consciously passed on these."

---

## Hygiene methodology (so this doc is honest)

These citations were collected by:
1. Reading `docs/current/AUDIT-03-quality.md` `Q-N` rows verbatim.
2. Reading `docs/current/CODE-AUDIT.md` `X-N` and per-file "N" notes.
3. Reading `docs/current/WS5-CODE-REVIEW.md` `r#` rows.
4. Walking the pyproject.toml [`tool.ruff.lint] ignore = [...]` list and citing each by audit doc.

If a future reader finds this doc *out of sync* with `pyproject.toml` (a `B###` is disable-able
here but enabled in `pyproject.toml`, or vice versa), that is a bug — file a fix-up commit.
