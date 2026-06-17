# Chain Probes — design (BUILT 2026-06-13)

**Status: implemented** in `bench.py` (probe registry + `run_probes`), hub
endpoints `/api/bench/probe*`, the Bench tab "🔬 Deep Probe" panel, and
`python bench.py --probe`. 16 probes across 5 layers; tests in
`tests/test_probes.py`. Runs persist to `data/bench/probe-<ts>.json`.


**Goal:** evolve the test bench from binary green/red into chain-ordered *probes*
that emit **interpretable data** and a **3-tier verdict** (`works` / `degraded` /
`broken`), so you can tell "actually works" from "merely passes". Built by
**extending `bench.py`** with a probe mode — same layer ordering, registry, and
hub tab; binary infra checks stay as-is.

## Data model

A probe returns, in addition to the existing `{status, detail}`:

```python
{
  "verdict": "works" | "degraded" | "broken" | "skip",
  "summary": "one-line human readout (what the data means)",
  "data":    { ...structured metrics / samples / artifacts... },
  "thresholds": "the rule that maps data → verdict (shown in UI)"
}
```

- `works` — does the real job, with healthy numbers.
- `degraded` — reachable and technically "passes", but the data shows it isn't
  doing the job well (the case current pass/fail hides — e.g. grammar honored
  but output empty, planner returns 1 entity when 2 were asked).
- `broken` — fails its purpose.
- Helper: `_probe(verdict, summary, thresholds, **data)` alongside `_ok/_fail`.

Verdict roll-up per layer = worst child. The chain stops being trustworthy at the
first `broken`, so the UI highlights the earliest break.

## What stays binary (data adds nothing)

Keep as plain `_ok/_fail`: `llama.health`, `llama.caps`, `llama.props` (alias
match), `godotai.status` (version), `godotai.bind`, `godotai.tools`,
`godotai.editor`, `godotai.guard`, `devforge.tools`, `ody.up`, `ody.reach`,
`ody.endpoint`. These are reachability/config gates — present or not.

---

## Layer 1 — llama (head of chain)

| Probe | Input | Data emitted | works / degraded / broken |
|---|---|---|---|
| `llama.throughput` | fixed 200-tok completion | `tok_per_sec, ttft_ms, gen_tok, prompt_tok` | ≥15 tok/s / 5–15 / <5 or error |
| `llama.context` | `/props` vs `stack.env` | `n_ctx_loaded, configured_ctx, kv_cache_type, batch` | loaded==configured / silently clamped lower / alias mismatch |
| `llama.grammar` ⬆ | completion forced to a tiny JSON via GBNF | `raw_output, parsed_ok, honored, gen_tok` | exact+parses / parses but extra tokens or slow / **grammar ignored (free text)** — this is the planner's lifeline |
| `llama.thinking` ⬆ | one chat turn (+`/no_think` if Qwen) | `content_chars, reasoning_chars, finish_reason` | content present, reasoning controlled / large reasoning leak / **empty content + reasoning dump (thinking trap)** |
| `llama.tools` ⬆ | obvious tool task | `emitted_tool_call, tool_name, finish_reason` | native tool call / mentions tool in prose only / no tool intent |

## Layer 2 — DevForge (planner → compiler → validator → completeness → executor)

The heart. Each probe runs a **fixed prompt against a fixed scene** and captures
one pipeline stage's artifact, so you see exactly where signal is lost.

| Probe | What it captures | Data emitted | works / degraded / broken |
|---|---|---|---|
| `devforge.plan` | `arch_delta` from a known prompt | `entities[], systems[], parents{}, gen_ms` | all expected entities w/ valid types / partial or extra / **empty delta** |
| `devforge.compile` | delta → operations | `op_count, ops[{type,parent,name}], paths_valid` | ops match + `/root/Main` paths / some wrong paths / 0 ops |
| `devforge.validate` | known-good + known-bad op sets | `valid_count, error_count, caught_bad_parent` | accepts good, rejects bad / misses a bad / rejects good |
| `devforge.completeness` | sparse scene (no light) | `injected[{type,parent}], parents_valid` | injects at `/root/Main` / injects but odd / **invalid parent** (regression guard for the bug just fixed) |
| `devforge.execute` ⬆ | full `apply_spec`, fixed prompt+scene | `ops_total, applied, errors, before_n, after_n, nodes_added[], ms` | applied==ops, 0 errors, nodes appear / partial / 0 applied or refuses |
| `devforge.roundtrip` | DevForge scene view vs godot-ai | `devforge_n, godot_n, paths_match` | match / count mismatch / can't fetch |

## Layer 3 — godot-ai (MCP bridge)

| Probe | Input | Data emitted | works / degraded / broken |
|---|---|---|---|
| `godotai.apply_latency` | create+delete a node | `create_ms, delete_ms, echoed_path` | fast round-trip / slow / error |
| `godotai.scene_fidelity` | `scene_get_hierarchy` | `node_count, depth, sample_paths` | expected shape / truncated oddly / error |

## Layer 4 — Godot runtime

| Probe | Input | Data emitted | works / degraded / broken |
|---|---|---|---|
| `runtime.launch` | `project_run` disposable scene, `autosave=False` | `launched, fps, boot_ms, log_errors[]` | FPS>0, no errors / launches w/ errors or low FPS / won't launch |
| `runtime.script_compile` | create+attach a tiny `.gd`, run | `parse_ok, compile_errors[]` | compiles / warnings / parse error |

## Layer 5 — Odysseus (product consumer)

| Probe | Input | Data emitted | works / degraded / broken |
|---|---|---|---|
| `odysseus.persona` ⬆ | live persona vs configured | `active_chars, matches_expected, first_120` | configured persona live / present but stale/clobbered / default/empty |
| `odysseus.generate` | tiny chat, web/RAG off | `content_chars, on_topic, reasoning_chars` | on-genre content / short or off / empty/error |
| `odysseus.tools` ⬆ | list MCP tools | `tool_count, devforge_present, namespaced_ok` | DevForge tools reachable / partial / none |
| `odysseus.retrieval` ⬆ | RAG query | `hits, top_doc, latency_ms` | relevant hit / weak / none |

⬆ = upgrade of an existing `bench.py` test to emit data.

---

## Surfacing

- **Hub Bench tab**: a "Probe (deep)" run mode. Each row shows the verdict chip
  (green/amber/red), the one-line summary, and an expandable JSON of `data` +
  the `thresholds` rule. Layer roll-up chips at top; earliest `broken` flagged.
- **CLI**: `python bench.py --probe [--layer llama]` prints summary + data; the
  data is also saved to `data/bench/probe-<ts>.json` (like shootout scorecards)
  so runs are comparable over time.
- Reuses the existing bundling/history so you can diff probe data run-to-run.

## Build order (once approved)

1. `_probe()` helper + result plumbing + registry `kind: "probe"` flag.
2. Layer 1 (llama) probes — fastest, head of chain.
3. Layer 2 (DevForge) probes — the highest-value signal.
4. Layers 3–5.
5. Hub tab probe mode + CLI `--probe` + per-run JSON persistence.
6. Unit tests (verdict mapping, data shape) per layer.

Open question for you: the fixed prompt+scene that Layer 2 probes run against —
use the **disposable `shootout.tscn`** (consistent, isolated, already built) or a
**new minimal `probe.tscn`** (even smaller — bare `Main` Node3D)?
