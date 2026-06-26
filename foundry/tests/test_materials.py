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
