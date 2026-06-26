"""Unit tests for materials.py — WS-3.1 new materials + seeded variation."""

import pytest
from materials import MATERIAL_PALETTE, material_ids, material_variation


def test_new_materials_exist():
    """WS-3.1: leather, ceramic, glazed, bronze, painted_wood are registered."""
    for name in ("leather", "ceramic", "glazed", "bronze", "painted_wood"):
        assert name in MATERIAL_PALETTE, f"{name} missing from MATERIAL_PALETTE"


def test_leather_is_fabric():
    assert MATERIAL_PALETTE["leather"]["family"] == "fabric"
    assert "base_rgb" in MATERIAL_PALETTE["leather"]
    assert "thread_rgb" in MATERIAL_PALETTE["leather"]


def test_ceramic_is_stone():
    assert MATERIAL_PALETTE["ceramic"]["family"] == "stone"
    assert MATERIAL_PALETTE["ceramic"]["metallic"] == 0.0


def test_glazed_is_stone_with_sheen():
    assert MATERIAL_PALETTE["glazed"]["family"] == "stone"
    assert MATERIAL_PALETTE["glazed"]["metallic"] > 0.0
    assert MATERIAL_PALETTE["glazed"]["roughness"] < 0.5


def test_bronze_is_metal():
    assert MATERIAL_PALETTE["bronze"]["family"] == "metal"
    assert MATERIAL_PALETTE["bronze"]["metallic"] == 1.0
    assert "tint_rgb" in MATERIAL_PALETTE["bronze"]


def test_painted_wood_is_wood():
    assert MATERIAL_PALETTE["painted_wood"]["family"] == "wood"
    assert "grain_light_rgb" in MATERIAL_PALETTE["painted_wood"]
    assert "grain_dark_rgb" in MATERIAL_PALETTE["painted_wood"]


def test_variation_is_deterministic():
    """Same seed always produces same variant."""
    mat = MATERIAL_PALETTE["worn_oak"]
    v1 = material_variation(mat, seed=42)
    v2 = material_variation(mat, seed=42)
    assert v1 == v2


def test_variation_different_seeds_differ():
    """Different seeds produce different variants."""
    mat = MATERIAL_PALETTE["worn_oak"]
    v1 = material_variation(mat, seed=1)
    v2 = material_variation(mat, seed=2)
    # At least one float value should be different
    any_diff = False
    for k in v1:
        if v1[k] != v2[k]:
            any_diff = True
            break
    assert any_diff, "variants should differ for different seeds"


def test_variation_preserves_family():
    """Variation does not change the material family."""
    for name in ("worn_oak", "rough_granite", "wrought_iron", "linen"):
        mat = MATERIAL_PALETTE[name]
        v = material_variation(mat, seed=7)
        assert v["family"] == mat["family"]


@pytest.mark.parametrize("seed", range(100))
def test_variation_roughness_in_range(seed):
    """Roughness stays in [0, 1] after jitter (parametrized over 100 seeds)."""
    mat = {"family": "stone", "base_rgb": (0.5, 0.5, 0.5), "mottle_rgb": (0.3, 0.3, 0.3), "roughness": 0.5, "metallic": 0.0}  # noqa: E501  test-data
    v = material_variation(mat, seed=seed)
    assert 0.0 <= v["roughness"] <= 1.0, f"roughness out of range at seed {seed}"


@pytest.mark.parametrize("seed", range(100))
def test_variation_metallic_in_range(seed):
    """Metallic stays in [0, 1] after jitter (parametrized over 100 seeds)."""
    mat = {"family": "metal", "tint_rgb": (0.1, 0.1, 0.1), "base_rgb": (0.2, 0.2, 0.2), "roughness": 0.4, "metallic": 0.5}  # noqa: E501  test-data
    v = material_variation(mat, seed=seed)
    assert 0.0 <= v["metallic"] <= 1.0, f"metallic out of range at seed {seed}"


def test_variation_returns_copy():
    """Variation returns a copy, not the original."""
    mat = MATERIAL_PALETTE["worn_oak"]
    v = material_variation(mat, seed=99)
    assert v is not mat
    v["roughness"] = 0.123
    assert mat["roughness"] != 0.123


def test_ids_returns_all():
    ids = material_ids()
    assert "worn_oak" in ids
    assert "leather" in ids
    assert "bronze" in ids
    assert "painted_wood" in ids
    assert len(ids) >= 13  # 8 original + 5 new


# ═══════════════════════════════════════════════════════════════════════════
#  PROMPT 6-A (per-instance HSV jitter) — TDD-RED
# ═══════════════════════════════════════════════════════════════════════════
# Queue scope: micro-jitter hue ±5°, saturation ±10%, value ±8%.  Per queue
# spec the seed is hash(entity_id + material_name) and the algorithm must
# work in HSV (not the existing per-channel RGB shift).
#
# These tests will FAIL on the current implementation because
# material_variation() shifts each RGB channel independently with a uniform
# ±0.05 (no HSV conversion, no saturation/value tracking) — three tests
# below show the algorithm visibly differs from "rotate hue, scale sat/val".
# Implementation in commit 1 replaces the RGB-shift block with an HSV
# conversion + bounded shift.

def test_variation_jitters_color_in_hsv_space():
    """PROMPT 6-A: material_variation uses HSV-space jitter, not per-channel RGB.

    After the algorithm change, hue/sat/val deltas are pulled from ONE rng
    stream and applied to each rgb triplet via colorsys.  Both wood colour
    channels must reflect the HSV jitter (currently both shift in lock-step
    under the RGB algorithm — a finger-print we no longer want).
    """
    mat = MATERIAL_PALETTE["worn_oak"]
    v = material_variation(mat, seed=42)
    # Wood: grain_light_rgb + grain_dark_rgb must both drift from base.
    assert v["grain_light_rgb"] != mat["grain_light_rgb"], (
        "HSV jitter did not move grain_light_rgb; algorithm still "
        "shifts RGB per-channel instead of via HSV conversion"
    )
    assert v["grain_dark_rgb"] != mat["grain_dark_rgb"], (
        "HSV jitter did not move grain_dark_rgb; algorithm still "
        "shifts RGB per-channel instead of via HSV conversion"
    )


def test_variation_rgb_channels_stay_in_unit_range():
    """PROMPT 6-A: HSV→RGB conversion clamps all channels to [0, 1] across
    many (material, seed) combinations so the bake step never sees -ve or
    >1 floats that would corrupt the base-colour PNG."""
    for name, base in MATERIAL_PALETTE.items():
        for seed in range(20):
            v = material_variation(base, seed=seed)
            for key, val in v.items():
                if (
                    isinstance(val, tuple)
                    and len(val) == 3
                    and all(isinstance(c, float) for c in val)
                ):
                    for ch_idx, ch in enumerate(val):
                        assert 0.0 <= ch <= 1.0, (
                            f"{name}.{key}[{ch_idx}] = {ch} "
                            f"out of [0,1] at seed={seed}"
                        )


def test_variation_visible_diff_for_grey_material():
    """PROMPT 6-A: HSV algorithm must drift grey materials visibly.

    Combined binary + soft quantitative (avoids single-seed brittleness
    that bit the parametrized-3.0-aim approach; seed=42 lands at
    delta=0.0287 - below the queue's 0.04 envelope anchor):
      - binary out[key] != base[key] anchors "jitter did something"
        (loose, robust to ANY rng outcome)
      - quantitative delta >= 0.02 anchors "drift within queue
        envelope edge" - tight enough to catch sub-envelope regressions
        (a future algo that drops V/S for S~0 inputs would land
        uniformly below 0.02 across multiple seeds).
    """
    base = MATERIAL_PALETTE["rough_granite"]
    for seed in (0, 7, 42):
        out = material_variation(base, seed=seed)
        for key in ("base_rgb", "mottle_rgb"):
            delta = max(abs(base[key][i] - out[key][i]) for i in range(3))
            # Binary backstop - any drift at all is acceptable.
            assert out[key] != base[key], (
                f"seed={seed} {key}: no drift - jitter no-op; HSV "
                "algorithm regressed"
            )
            # Soft quantitative anchor within the queue envelope.
            assert delta >= 0.02, (
                f"seed={seed} {key} delta={delta:.4f} below 0.02 "
                "queue-envelope anchor; sub-envelope drift suggests an "
                "algorithm regression in the V/S path"
            )




def test_variation_hsv_path_remains_deterministic():
    """PROMPT 6-A: the new HSV implementation is still deterministic — same
    seed → byte-identical output dict (catches accidental `random.seed()`
    or unseeded RNG introductions during the algorithm swap).
    """
    for name, base in MATERIAL_PALETTE.items():
        a = material_variation(base, seed=7)
        b = material_variation(base, seed=7)
        assert a == b, f"{name}: HSV algorithm non-deterministic at seed=7"


# ── PROMPT 6-A HARD-RED: new public helpers required by the queue binding

def test_jitter_seed_deterministic_for_same_inputs():
    """PROMPT 6-A: jitter_seed(entity_id, material_name) is a deterministic
    int derived from hash(entity_id + material_name).  Same inputs → same int.
    """
    from materials import jitter_seed  # HARD RED: helper does not exist yet
    a = jitter_seed("table_0", "worn_oak")
    b = jitter_seed("table_0", "worn_oak")
    assert a == b
    # 64-bit unsigned range
    assert isinstance(a, int)
    assert 0 <= a < 2 ** 64


def test_jitter_seed_distinct_for_distinct_inputs():
    """PROMPT 6-A: jitter_seed differs across distinct (entity_id, material)
    pairs so per-instance variation actually fires.  Allows up to 1
    collision per 20 distinct (entity_id, material) inputs — SHA-256 in a
    64-bit space can't hit that in the test set.
    """
    from materials import jitter_seed  # HARD RED: helper does not exist yet
    seen: set[int] = set()
    for i in range(20):
        seen.add(jitter_seed(f"entity_{i}", "worn_oak"))
    assert len(seen) >= 19, f"too many seed collisions: {len(seen)}/20"


def test_jitter_for_returns_bounded_hsv_deltas():
    """PROMPT 6-A: jitter_for(entity_id, material_name) returns a 3-tuple
    (dh_deg, ds_frac, dv_frac) inside the queue bounds:
        hue degrees       in [-5, +5]
        saturation frac   in [-0.10, +0.10]
        value frac        in [-0.08, +0.08]
    Pure function; same inputs → same tuple.  Distinct inputs → distinct
    tuples (within rare-collision tolerance).
    """
    from materials import jitter_for  # HARD RED: helper does not exist yet

    # Bounds check across 50 (entity_id, material) pairs.
    for i in range(50):
        dh, ds, dv = jitter_for(f"entity_{i}", "worn_oak")
        assert -5.0 <= dh <= 5.0, f"hue out of bounds at i={i}: {dh}"
        assert -0.10 <= ds <= 0.10, f"sat out of bounds at i={i}: {ds}"
        assert -0.08 <= dv <= 0.08, f"val out of bounds at i={i}: {dv}"

    # Determinism.
    a = jitter_for("table_0", "worn_oak")
    b = jitter_for("table_0", "worn_oak")
    assert a == b

    # Distinct inputs produce distinct outputs.
    distinct = {
        jitter_for(f"entity_{i}", "worn_oak") for i in range(20)
    }
    assert len(distinct) >= 18, f"too many jitter collisions: {len(distinct)}/20"


# ── PROMPT 6-A code-review fixes ───────────────────────────────────────────

def test_jitter_seed_nul_separator_no_boundary_collision():
    """PROMPT 6-A review fix: the older f"{entity_id}_{material_name}"
    join was ambiguous - ('ab', 'cd_ef') and ('ab_cd', 'ef') both produced
    the same digest.  The NUL-separator join now used by jitter_seed must
    NOT have that collision.  Every legal (left, right) pair is encoded
    uniquely.
    """
    from materials import jitter_seed
    s_ab_cd_ef = jitter_seed("ab", "cd_ef")
    s_ab_cd    = jitter_seed("ab_cd", "ef")
    assert s_ab_cd_ef != s_ab_cd, (
        "jitter_seed boundary collision regressed: ('ab','cd_ef') and "
        "('ab_cd','ef') must produce distinct seeds under the NUL "
        "separator; if equal, the join form has regressed"
    )


def test_material_variation_locks_step_within_one_call():
    """PROMPT 6-A review fix - DELIBERATE design: ONE call to
    material_variation() applies a SINGLE (dh, ds, dv) triple to ALL rgb
    triplets in the material so the family signature (light + dark wood
    drift together, base + mottle drift together) is preserved within one
    asset.  Per-key independent jitter would let grain_light drift cool
    while grain_dark stays warm within a single piece of wood, reading
    as incoherent material.

    This test freezes the behaviour: if a future refactor splits the
    triple into per-key draws, this assertion fires.
    """
    import colorsys as _cs
    # worn_oak has grain_light_rgb + grain_dark_rgb - two keys to compare.
    mat = MATERIAL_PALETTE["worn_oak"]
    out = material_variation(mat, seed=42)
    h_base_l, _, _ = _cs.rgb_to_hsv(*mat["grain_light_rgb"])
    h_base_d, _, _ = _cs.rgb_to_hsv(*mat["grain_dark_rgb"])
    h_out_l, _, _  = _cs.rgb_to_hsv(*out["grain_light_rgb"])
    h_out_d, _, _  = _cs.rgb_to_hsv(*out["grain_dark_rgb"])
    # Wrap-aware hue delta (HSV hue is in 0..1; take the smaller arc).
    def _delta(a, b):
        d = abs(a - b) % 1.0
        return min(d, 1.0 - d)
    delta_l = _delta(h_out_l, h_base_l)
    delta_d = _delta(h_out_d, h_base_d)
    assert abs(delta_l - delta_d) < 1e-9, (
        f"locked-step drift violated: grain_light hue moved by {delta_l:.6f} "
        f"but grain_dark moved by {delta_d:.6f}; design says all rgb keys "
        f"within one call share the same dh (and thus rotate identically in"
        f" hue)"
    )


# ───── PROMPT 6-A 2/4: apply_instance_jitter public surface ─────

def test_apply_instance_jitter_returns_a_copy_not_mutation_of_input():
    """PROMPT 6-A 2/4: apply_instance_jitter() returns a NEW dict;
    the input dict's object identity is preserved (no in-place mutation).
    Critical invariant: hot-path callers can safely re-use a single
    MATERIAL_PALETTE entry across many asset_ids without cross-pollution.
    """
    from materials import MATERIAL_PALETTE, apply_instance_jitter
    base = MATERIAL_PALETTE["worn_oak"]
    snapshot = dict(base)  # deep copy of the outermost dict (RGB tuples are immutable)
    out = apply_instance_jitter(base, asset_id="chair_a", material_name="worn_oak")
    assert out is not base, "must return a NEW dict reference (not the input)"
    assert base == snapshot, (
        "input dict must be unchanged after apply_instance_jitter; if this fails, "
        "the helper is mutating MATERIAL_PALETTE in-place and seeds would alias"
    )


def test_apply_instance_jitter_produces_new_variant_for_palette_entry():
    """PROMPT 6-A 2/4: per-instance jitter must produce a NEW variant for
    a known palette entry. We sweep across asset_ids 0..9 and require
    >= 8 of them to yield a distinct grain_light_rgb from the base.
    (Two collisions in ten SHA-256-derived seeds is mathematically unlikely.)
    """
    from materials import MATERIAL_PALETTE, apply_instance_jitter
    base = MATERIAL_PALETTE["worn_oak"]
    base_light = base["grain_light_rgb"]
    distinct = 0
    for i in range(10):
        out = apply_instance_jitter(base, asset_id=f"chair_{i}", material_name="worn_oak")
        if out["grain_light_rgb"] != base_light:
            distinct += 1
    assert distinct >= 8, (
        f"per-instance jitter produced only {distinct}/10 distinct variants of "
        f"grain_light_rgb vs base; expected >= 8 (the lockstep design should "
        f"vary the family hue within the +/-5 deg envelope for almost every id)"
    )


def test_apply_instance_jitter_is_deterministic_for_same_inputs():
    """PROMPT 6-A 2/4: identical (mat, asset_id, material_name) -> byte-identical
    copy on every call. Two independent invocations must compare equal.
    """
    from materials import MATERIAL_PALETTE, apply_instance_jitter
    a = apply_instance_jitter(MATERIAL_PALETTE["dark_walnut"], "shelf_42", "dark_walnut")
    b = apply_instance_jitter(MATERIAL_PALETTE["dark_walnut"], "shelf_42", "dark_walnut")
    assert a == b, (
        "two independent apply_instance_jitter calls with identical inputs "
        "differed - SHA-256 seed determinism regression"
    )


def test_apply_instance_jitter_distinct_for_distinct_asset_ids_same_palette():
    """PROMPT 6-A 2/4: load-bearing queue-concern test -- the prior
    `distinct_for_distinct_material_names` was too weak (it used two
    DIFFERENT base palettes, so it would pass even if SHA-256 dedup
    were completely broken, since the BASE PALETTES already diverge).

    This is the actual user-visible scenario: two tables of the SAME
    material (`worn_oak`) with DIFFERENT asset_ids must look distinct.
    If SHA-256 dedup is broken the test FAILS because the per-instance
    RNG stream would collide; the prior weak test could not catch this
    regression."""
    from materials import MATERIAL_PALETTE, apply_instance_jitter
    base = MATERIAL_PALETTE["worn_oak"]
    a = apply_instance_jitter(base, asset_id="table_alpha", material_name="worn_oak")
    b = apply_instance_jitter(base, asset_id="table_beta",  material_name="worn_oak")
    # PROMPT 6-A reviewer-4 final: a != b is the rigorous invariant --
    # _apply_hsv_jitter_to_rgbs only mutates RGB triplets (locked-step),
    # so dict inequality is *equivalent* to "any RGB key differs." The
    # prior grain_light_rgb-specific check was brittle belt-and-suspenders:
    # for worn_oak only family+grain_light+grain_dark are present, so a
    # per-key sweep of 6 names collapses to 2. Keeping a != b matches
    # the queue's user-facing claim ("two same-material props look
    # visibly different") without over-promising coverage we can't
    # deliver for a half-formed palette like worn_oak.
    assert a != b, (
        f"two same-palette different-asset_id jittered variants compared "
        f"equal (grain_light a={a.get('grain_light_rgb')!r}, "
        f"grain_light b={b.get('grain_light_rgb')!r}) -- SHA-256 dedup "
        f"regression: per-instance jitter should produce distinct RGB "
        f"for distinct asset_ids"
    )


def test_apply_instance_jitter_distinct_for_distinct_material_names():
    """PROMPT 6-A 2/4 (orthogonal smoke): same asset_id paired with two
    distinct material names produces visibly different variants. NOTE
    this is dominated by the BASE PALETTE difference, not by the
    SHA-256 seed; the load-bearing same-palette different-asset_id
    test is `test_apply_instance_jitter_distinct_for_distinct_asset_ids_same_palette`
    above. This test stays as an orthogonal seed-keyspace smoke."""
    from materials import MATERIAL_PALETTE, apply_instance_jitter
    a = apply_instance_jitter(MATERIAL_PALETTE["worn_oak"], "table_x", "worn_oak")
    b = apply_instance_jitter(MATERIAL_PALETTE["dark_walnut"], "table_x", "dark_walnut")
    assert a != b
    assert a["grain_light_rgb"] != b["grain_light_rgb"]


def test_apply_instance_jitter_stays_within_queue_envelope():
    """PROMPT 6-A 2/4: per-channel max drift vs the base palette entry
    must stay within the queue-envelope guard (h +/-5 deg, S +/-10 %,
    V +/-8 %; round-trip RGB error is bounded). Per-channel max delta
    <= 0.18 is a conservative ceiling that absorbs the S+V combined
    envelope plus a small numeric-RGB-roundtrip float error.
    """
    from materials import MATERIAL_PALETTE, apply_instance_jitter
    base = MATERIAL_PALETTE["worn_oak"]
    FLOOR = 0.18
    for i in range(20):
        out = apply_instance_jitter(base, asset_id=f"chair_e_{i}", material_name="worn_oak")
        for key in ("grain_light_rgb", "grain_dark_rgb"):
            delta = max(abs(base[key][c] - out[key][c]) for c in range(3))
            assert delta <= FLOOR, (
                f"{key} drifted {delta:.4f} from base; max-permitted is {FLOOR}; "
                f"this asset_id sent the jitter out of the queue envelope"
            )


def test_apply_instance_jitter_grey_material_still_shifts_visibly():
    """PROMPT 6-A 2/4: near-grey materials (S approx 0 makes hue rotation
    invisible on RGB) must still differ from the base via the value and/or
    saturation jitter. This is the per-instance counterpart to the
    material_variation grey guard test."""
    from materials import MATERIAL_PALETTE, apply_instance_jitter
    base = MATERIAL_PALETTE["rough_granite"]
    # Loop a handful of asset_ids -- if a particular seed landed on a
    # trivially-zero (dS=0, dV=0) triple, another seed almost certainly
    # won't. Binary != is a robust backstop: at least one channel moved.
    any_changed = False
    for i in range(5):
        out = apply_instance_jitter(base, asset_id=f"granite_{i}", material_name="rough_granite")
        if out["base_rgb"] != base["base_rgb"]:
            any_changed = True
            break
        if out["mottle_rgb"] != base["mottle_rgb"]:
            any_changed = True
            break
    assert any_changed, (
        "rough_granite is a grey material (S approx 0 -> hue rotation invisible), "
        "but the value/saturation jitter must still produce a visible shift on "
        "at least one channel for at least one of 5 seeds"
    )
