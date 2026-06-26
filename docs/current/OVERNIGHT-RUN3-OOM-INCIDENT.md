# Incident report: overnight_run3 OOM cascade → forced power-off

**Date:** 2026-06-22 16:38 – 2026-06-23 04:41 (CEST)
**Reported symptom:** "Hyprland crash"
**Actual cause:** Hyprland never crashed. A background asset-generation job
exhausted system RAM repeatedly overnight; the desktop became unresponsive
and the user power-cycled the machine, tearing down the whole session.

## Summary

`/tmp/overnight_run3.sh` (launched from a Claude Code session in this repo)
ran `foundry/overnight_assets.py` to batch-generate ~35 game-asset GLBs, one
Python process per asset by design. Each process calls
`proxy.voxelize_glb()`, which calls `trimesh.Trimesh.contains()` to test
voxel-grid points against the mesh surface. The `foundry/.venv` is missing
`embreex` (the modern pyembree replacement), so trimesh falls back to its
pure-NumPy ray-triangle intersector. That fallback builds an
`O(query_points × triangles)` intermediate array with no chunking and no
upper bound.

Over roughly 12 hours, six separate per-asset processes ballooned to
17–23 GB RSS each (host: 31 GB RAM, **no swap**) and were individually
OOM-killed by the kernel. The per-process batch design meant the script
"worked" — it kept going after each kill — but it hammered the box with
repeated memory-pressure events all night. By 04:41 the desktop was
unresponsive enough that the power button was pressed (short press, picked
up by `systemd-logind`), which powered the machine off and tore down the
entire Hyprland session along with everything else in it. That shutdown is
what looked like a "Hyprland crash."

## Evidence

### Per-asset OOM kills (`journalctl -b -1 -k`)

All killed processes are named `python`, all in
`/user.slice/user-1000.slice/user@1000.service/kitty-4703-0.scope` — i.e.
the per-asset subprocess spawned by `overnight_run3.sh`'s loop:

| Time (Jun 22/23) | PID | anon-rss |
|---|---|---|
| 16:38:23 | 2759581 | 19.3 GB |
| 17:04:58 | 2879342 | 19.4 GB |
| 03:27:10 | 70058   | 15.9 GB |
| 03:42:39 | 149915  | 18.7 GB |
| 03:51:31 | 203877  | 18.9 GB |
| 03:59:51 | 239732  | 20.1 GB |

### Reproduction (capped in a cgroup so it couldn't repeat the damage)

```
crate_weathered_pine.glb   (108 faces)  → voxelize_glb() peak RSS: 1.5 GB
tree_weathered_pine.glb   (1660 faces)  → voxelize_glb() peak RSS: 7.3 GB
```

Confirms memory cost scales with mesh triangle count and has no bound —
consistent with the 17–23 GB kills above for whatever (higher-poly) assets
were being processed at those times.

### Shutdown trigger (`journalctl -b -1 -u systemd-logind`)

```
Jun 23 04:41:57 arch systemd-logind[587]: Power key pressed short.
Jun 23 04:41:57 arch systemd-logind[587]: Powering off...
Jun 23 04:41:57 arch systemd-logind[587]: System is powering down.
```

This is a physical power-button press, not a kernel panic, not a Hyprland
segfault, and not a fresh OOM kill at that exact moment. The
`systemd[676]: user-1000.slice: The kernel OOM killer killed some processes
in this unit` lines logged during the shutdown sequence are systemd's
cumulative accounting of the earlier per-asset kills above, not a new event.

## Root cause

`foundry/proxy.py:_sample_voxels()` calls `mesh.contains(points)` on the
full `resolution³` point grid (262,144 points at `resolution=64`) in one
shot, with no chunking. Without `embreex`, trimesh's fallback ray-triangle
intersector allocates intermediate arrays proportional to
`points × mesh.faces`, which has no ceiling — a sufficiently complex
generated mesh can consume tens of GB in a single call. Combined with a
31 GB host that has **no swap configured**, the kernel has zero cushion
before it has to start killing processes.

## Fixes

1. **`foundry/proxy.py` — APPLIED** (commit `9b18f34`). `_contains_chunked()`
   runs containment in *face-aware* batches (`batch × faces` under an ~64 MB
   budget), `_decimate_to_cap()` caps meshes at 20k faces, `resolution` is
   clamped to ≤96, the output dir is auto-created, and `resolution=1` no longer
   divides by zero. `embreex` is now installed + pinned in `requirements.txt`
   for BVH-accelerated containment. **Verified:** the tree case (1660 faces)
   drops from **7.3 GB → 409 MB** (chunked) / **181 MB, 0.2 s** (with embreex).
   5 regression tests in `tests/test_proxy_memory.py`.
2. **System — STILL RECOMMENDED (user action).** Add swap. A no-swap 31 GB box
   means any single runaway process can take down unrelated processes (incl. the
   desktop session) with no warning window. The proxy fix removes *this* trigger,
   but swap is the defense-in-depth that catches the next unknown one.

## Files / scripts referenced

- `foundry/overnight_assets.py` — per-asset batch driver (`prep_one`)
- `foundry/proxy.py` — `voxelize_glb()` / `_sample_voxels()` (the leak site)
- `/tmp/overnight_run3.sh` — generated nohup wrapper, no longer on disk
  (tmpfs, cleared by the reboot); recovered from the Claude Code session
  transcript that created it (`.claude/projects/-home-mrg-dev-games-Forge/c6d22b09-646f-4afd-a8ec-9cd738d5ab2f.jsonl`)
