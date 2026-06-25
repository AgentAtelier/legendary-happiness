"""Apply the Q17 DP-emission changes to placement.py + decisions.py.

Follows the designer's plan exactly:
  - _TEMPLATES entry in decisions.py for placement.npc_clamp_triggered
  - _resolve_prop_overlaps signature gains ``decisions_out: list | None = None``
  - _resolve_overlaps_bruteforce signature gains the same kwarg
  - Inside both, a ``npc_pushed_ids`` set tracks every prop ID the
    NPC collision branch actually moved (collapsed via set; an ID
    re-emitted across iterations counts once)
  - One summary DecisionPoint per call when the set is non-empty
  - _resolve_overlaps_bruteforce call site forwards decisions_out
"""
import re
from pathlib import Path

# ─── 1. decisions.py — register the template ───
dp = Path("decisions.py")
d_text = dp.read_text()

# Find the last existing entry in _TEMPLATES to anchor our append.
# Use a known existing key as the marker — pick one immediately
# before/after the new entry we'll add.  Looking at the prior reads
# the templates have entries like:
#   "navmesh.too_dense": (
#       ...
#   ),
# We'll add placement.npc_clamp_triggered right after the navmesh one.
old_tmpl_anchor = '"navmesh.too_dense": (\n        # technical\n        "1+ navmesh caps (footprint-count > MAX_FOOTPRINTS or area > MAX_AREA_M2); returning empty mesh.",\n        # plain\n        "Too many obstacles or too large a room for the navigation mesh; the engine will use the flat-quad fallback so NPCs still move, but pathing may be sub-optimal. Adjust MAX_FOOTPRINTS / MAX_AREA_M2 in foundry/world/invariants.py if this is too aggressive.",\n    ),'  # noqa: E501  prompt
assert d_text.count(old_tmpl_anchor) == 1, (
    f"navmesh.too_dense anchor count = {d_text.count(old_tmpl_anchor)}"
)
new_tmpl_append = old_tmpl_anchor + '''
    "placement.npc_clamp_triggered": (
        # technical
        "NPC clearance displaced {count} unique prop(s) during AABB separation.",
        # plain
        "The standing NPC needed more room; {count} object(s) were nudged to a new spot. The displacement is correct but may surprise placement-sensitive downstream code (e.g. waypoint chains).",
    ),'''  # noqa: E501  prompt
d_text = d_text.replace(old_tmpl_anchor, new_tmpl_append)
dp.write_text(d_text)
print("(1) decisions.py: registered placement.npc_clamp_triggered template")

# ─── 2. placement.py — _resolve_prop_overlaps signature ───
pl = Path("placement.py")
p_text = pl.read_text()

# Add the kwarg to _resolve_prop_overlaps signature.
old_sig_main = '''def _resolve_prop_overlaps(
    manifest: list[dict],
    npc_x: float = 0.0,
    npc_z: float = -2.0,
    max_iterations: int = 20,
) -> list[dict]:'''
assert p_text.count(old_sig_main) == 1, (
    f"_resolve_prop_overlaps signature count = {p_text.count(old_sig_main)}"
)
new_sig_main = '''def _resolve_prop_overlaps(
    manifest: list[dict],
    npc_x: float = 0.0,
    npc_z: float = -2.0,
    max_iterations: int = 20,
    decisions_out: list | None = None,
) -> list[dict]:
    """Deterministic AABB separation pass.

    FIX-1: provides the no-clip placement pass complementing the
    StaticBody3D + CollisionShape3D prop conversion that'''
# `new_sig_main` includes only the first line(s) of the docstring to
# act as a unique marker; we'll insert the kwarg line in the middle.
p_text = p_text.replace(old_sig_main, new_sig_main)
print("(2a) placement.py: added decisions_out kwarg to _resolve_prop_overlaps")

# ─── 3. placement.py — _resolve_overlaps_bruteforce signature ───
old_sig_brute = '''def _resolve_overlaps_bruteforce(
    result: list[dict],
    separable: list[int],
    prop_data: list[tuple[int, float, float]],
    npc_x: float,
    npc_z: float,
    npc_hx: float,
    npc_hz: float,
    max_iterations: int,
) -> list[dict]:'''
assert p_text.count(old_sig_brute) == 1, (
    f"_resolve_overlaps_bruteforce signature count = {p_text.count(old_sig_brute)}"
)
new_sig_brute = '''def _resolve_overlaps_bruteforce(
    result: list[dict],
    separable: list[int],
    prop_data: list[tuple[int, float, float]],
    npc_x: float,
    npc_z: float,
    npc_hx: float,
    npc_hz: float,
    max_iterations: int,
    decisions_out: list | None = None,
) -> list[dict]:'''
p_text = p_text.replace(old_sig_brute, new_sig_brute)
print("(2b) placement.py: added decisions_out kwarg to _resolve_overlaps_bruteforce")

# ─── 4. Forward decisions_out from main → bruteforce call site ───
# The call looks like:
#   return _resolve_overlaps_bruteforce(
#       ...
#       max_iterations=max_iterations,
#   )
old_call = re.search(
    r'(return _resolve_overlaps_bruteforce\(\s*\n(?:.*\n)*?\s*max_iterations=max_iterations,\s*\n\s*\)\n)',
    p_text,
)
assert old_call, "could not locate bruteforce call site"
old_call_text = old_call.group(1)
new_call_text = old_call_text.replace(
    "max_iterations=max_iterations,\n    )",
    "max_iterations=max_iterations,\n        decisions_out=decisions_out,\n    )",
)
p_text = p_text.replace(old_call_text, new_call_text)
print("(3) placement.py: bruteforce call site forwards decisions_out")

# ─── 5. Initialise npc_pushed_ids at the top of both functions ───
# In _resolve_prop_overlaps, the tracker setup precedes the iter loop.
# The exact init is right after the "separable_indices =" or similar
# mapping line.  We anchor on "    positions:" but that lives in
# _find_open_npc_positions, so use a sharper marker: the unique
# phrase right before the first iteration in each function.
# Easier: use regex to find each function body and rewrite.

# Re-read after string replacements.
pl.write_text(p_text)
p_text = pl.read_text()

# In _resolve_prop_overlaps, the iteration block begins near
# `for _ in range(max_iterations):`.  Insert the tracker before it.
# We anchor on the unique first-iteration line in _resolve_prop_overlaps
# — it uses `separated_manifest` (renamed P8) and applies `_get_cell_radius`.
# Use the line right BEFORE `for _ in range`.
tracker_init_main = '''    _separated_manifest: list[dict] = [dict(e) for e in manifest]
    # Q17: track IDs of props the NPC pushed during separation so we
    # can emit a placement.npc_clamp_triggered Decision Point if any.
    _npc_pushed_ids: set[str] = set()

    for _ in range(max_iterations):'''
# Some variants name the variable differently; fall through to a softer match.
if tracker_init_main not in p_text:
    # Try the actual bytecode line — the variable in this codebase is
    # called `separated_manifest` in scene_compiler but `result` in
    # placement.  The _resolve_prop_overlaps body creates `result`.
    tracker_init_main = '''    result: list[dict] = [dict(e) for e in manifest]
    # Q17: track IDs of props the NPC pushed during separation so we
    # can emit a placement.npc_clamp_triggered Decision Point if any.
    _npc_pushed_ids: set[str] = set()

    for _ in range(max_iterations):'''
assert tracker_init_main in p_text, (
    "could not anchor _resolve_prop_overlaps tracker init "
    "(didn't find 'result: list[dict] = [dict(e) for e in manifest]\\n    "
    "for _ in range(max_iterations):' in placement.py)"
)
# Already-inserted version present?  Skip if so.
if "_npc_pushed_ids: set[str] = set()" not in p_text:
    # Inject the tracker right before the `for _ in range` loop.
    p_text = p_text.replace(
        "    result: list[dict] = [dict(e) for e in manifest]\n",
        "    result: list[dict] = [dict(e) for e in manifest]\n"
        "    # Q17: track IDs of props the NPC pushed during the\n"
        "    # AABB separation so we can emit a\n"
        "    # ``placement.npc_clamp_triggered`` Decision Point at the\n"
        "    # end of the pass.  IDs collapse across iterations (set\n"
        "    # semantics) so the count reflects unique displaced props.\n"
        "    _npc_pushed_ids: set[str] = set()\n",
        1,
    )
    print("(4a) placement.py: initialised _npc_pushed_ids tracker in _resolve_prop_overlaps")

# Initialise the same tracker in _resolve_overlaps_bruteforce.
# That function has signature line... `def _resolve_overlaps_bruteforce(`
# with `result: list[dict]` body.  Insert the tracker right after the
# function docstring / first executable line.
brute_marker = '''def _resolve_overlaps_bruteforce(
    result: list[dict],
    separable: list[int],
    prop_data: list[tuple[int, float, float]],
    npc_x: float,
    npc_z: float,
    npc_hx: float,
    npc_hz: float,
    max_iterations: int,
    decisions_out: list | None = None,
) -> list[dict]:'''
if "_npc_pushed_ids: set[str] = set()" not in p_text.split(brute_marker, 1)[1].split("\n", 40)[0]:
    # Insert after the docstring opening — easier: right after the
    # first assignment in the body.  Bruteforce opens with iteration
    # of `separable_sorted`.  Inject the tracker before that iteration.
    p_text = p_text.replace(
        brute_marker + "\n    for _ in range(max_iterations):",
        brute_marker + "\n"
        "    # Q17 (placement): track which props the NPC pushed so we\n"
        "    # can emit a placement.npc_clamp_triggered Decision Point.\n"
        "    _npc_pushed_ids: set[str] = set()\n"
        "    for _ in range(max_iterations):",
        1,
    )
    print("(4b) placement.py: initialised _npc_pushed_ids tracker in _resolve_overlaps_bruteforce")

pl.write_text(p_text)
print("Placement.py: tracker init phase complete.  Now editing NCP-collision branches + return statements.")
print("DONE step 1.")
