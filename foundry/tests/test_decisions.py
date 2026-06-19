"""TDD tests for foundry.decisions — the Decision Point structured-event model.

Decision Points are the pipeline's explainable, recoverable-failure layer:
the pipeline never blocks, it emits structured events. Two-register messages
(plain + technical) come from hand-authored templates filled with the
context dict. Presentation lives ONLY in render_cli.
"""

from __future__ import annotations

import json

import pytest


# ── SEVERITY / dataclass shape ─────────────────────────────────────


def test_severity_constants_exist():
    from decisions import SEVERITY
    # SEVERITY is a container of the four known severities
    expected = {"info", "assumption", "ambiguous", "error"}
    assert expected.issubset(set(SEVERITY))


def test_choice_dataclass_shape():
    from decisions import Choice

    c = Choice(label="Wrought iron", plain="dark tinted metal", apply={"field": "material", "value": "wrought_iron"})
    assert c.label == "Wrought iron"
    assert c.plain == "dark tinted metal"
    assert c.apply == {"field": "material", "value": "wrought_iron"}
    assert c.__dataclass_params__.frozen  # @dataclass(frozen=True)


def test_decision_point_dataclass_shape():
    from decisions import Choice, DecisionPoint

    choices = (Choice(label="X", plain="x", apply={"k": 1}),)
    dp = DecisionPoint(
        code="material.unspecified_defaulted",
        stage="planner",
        severity="assumption",
        technical="no material keyword matched; defaulted to worn_oak.",
        plain="You didn't name a material, so I used worn_oak.",
        context={"family": "wood", "resolved": "worn_oak"},
        choices=choices,
    )
    assert dp.code == "material.unspecified_defaulted"
    assert dp.stage == "planner"
    assert dp.severity == "assumption"
    assert dp.choices == choices
    assert dp.__dataclass_params__.frozen  # frozen


# ── Template registry & make_decision ──────────────────────────────


def test_make_decision_fills_both_registers_from_templates():
    """Templates are .format()-ed with the context dict."""
    from decisions import Choice, make_decision

    choices = (Choice(label="walnut", plain="dark brown walnut", apply={"field": "material", "value": "dark_walnut"}),)
    dp = make_decision(
        code="material.family_defaulted",
        stage="planner",
        severity="assumption",
        context={"family": "wood", "resolved": "worn_oak"},
        choices=choices,
    )
    assert dp.code == "material.family_defaulted"
    assert dp.stage == "planner"
    assert dp.severity == "assumption"
    assert dp.context == {"family": "wood", "resolved": "worn_oak"}
    assert dp.choices == choices
    # Templates filled from context
    assert dp.plain == "You asked for wood, so I used worn_oak. You can switch to another wood."
    assert dp.technical == "material family=wood has multiple members; defaulted to worn_oak."


def test_make_decision_unspecified_template():
    """The other registered code's templates fill correctly."""
    from decisions import Choice, make_decision

    choices = (Choice(label="oak", plain="warm brown oak", apply={"field": "material", "value": "worn_oak"}),)
    dp = make_decision(
        code="material.unspecified_defaulted",
        stage="planner",
        severity="assumption",
        context={"resolved": "worn_oak"},
        choices=choices,
    )
    assert dp.plain == "You didn't name a material, so I used worn_oak."
    assert dp.technical == "no material keyword matched; defaulted to worn_oak."


def test_make_decision_unknown_code_raises():
    """An unknown code is a programming error — fail loud."""
    from decisions import Choice, make_decision

    with pytest.raises(KeyError):
        make_decision(
            code="does.not.exist",
            stage="planner",
            severity="info",
            context={},
            choices=(),
        )


# ── to_dict / JSON round-trip ──────────────────────────────────────


def test_to_dict_is_json_serializable():
    """to_dict output round-trips through json.dumps."""
    from decisions import Choice, make_decision, to_dict

    choices = (
        Choice(label="walnut", plain="dark walnut", apply={"field": "material", "value": "dark_walnut"}),
        Choice(label="pine", plain="weathered pine", apply={"field": "material", "value": "weathered_pine"}),
    )
    dp = make_decision(
        code="material.family_defaulted",
        stage="planner",
        severity="assumption",
        context={"family": "wood", "resolved": "worn_oak"},
        choices=choices,
    )
    d = to_dict(dp)

    # choices became dicts
    assert isinstance(d["choices"], list)
    assert all(isinstance(c, dict) for c in d["choices"])
    assert d["choices"][0]["label"] == "walnut"
    assert d["choices"][0]["apply"] == {"field": "material", "value": "dark_walnut"}

    # json.dumps works
    serialized = json.dumps(d)
    assert isinstance(serialized, str)
    # And round-trips
    loaded = json.loads(serialized)
    assert loaded == d


def test_to_dict_preserves_all_top_level_fields():
    from decisions import Choice, make_decision, to_dict

    dp = make_decision(
        code="material.unspecified_defaulted",
        stage="planner",
        severity="assumption",
        context={"resolved": "worn_oak"},
        choices=(Choice(label="oak", plain="oak", apply={"field": "material", "value": "worn_oak"}),),
    )
    d = to_dict(dp)
    for k in ("code", "stage", "severity", "technical", "plain", "context", "choices"):
        assert k in d, f"Missing key: {k}"


# ── render_cli presentation ────────────────────────────────────────


def test_render_cli_shows_plain_and_technical_and_numbered_choices():
    """The dual-register output includes plain, technical, and numbered choices
    with their apply override shown."""
    from decisions import Choice, make_decision, render_cli

    choices = (
        Choice(label="Wrought iron", plain="dark tinted metal", apply={"field": "material", "value": "wrought_iron"}),
        Choice(label="Granite", plain="mottled grey stone", apply={"field": "material", "value": "rough_granite"}),
    )
    dp = make_decision(
        code="material.family_defaulted",
        stage="planner",
        severity="assumption",
        context={"family": "metal", "resolved": "wrought_iron"},
        choices=choices,
    )
    out = render_cli([dp])
    # Plain line
    assert "You asked for metal" in out
    assert "wrought_iron" in out
    # Technical line is clearly marked (the spec says "clearly-marked")
    assert "material family=metal" in out
    # Numbered choices with label + plain + apply override
    assert "1)" in out
    assert "Wrought iron" in out
    assert "dark tinted metal" in out
    assert "set material=wrought_iron" in out or "material=wrought_iron" in out
    assert "2)" in out
    assert "Granite" in out
    assert "set material=rough_granite" in out or "material=rough_granite" in out


def test_render_cli_omits_info_decisions():
    """`info` is carried but NOT rendered (per spec)."""
    from decisions import Choice, make_decision, render_cli

    visible_dp = make_decision(
        code="material.unspecified_defaulted",
        stage="planner",
        severity="assumption",
        context={"resolved": "worn_oak"},
        choices=(Choice(label="oak", plain="oak", apply={"field": "material", "value": "worn_oak"}),),
    )
    quiet_dp = make_decision(
        code="material.unspecified_defaulted",
        stage="planner",
        severity="info",
        context={"resolved": "worn_oak"},
        choices=(Choice(label="oak", plain="oak", apply={"field": "material", "value": "worn_oak"}),),
    )
    out = render_cli([visible_dp, quiet_dp])
    # Only the visible one appears
    assert out.count("You didn't name a material") == 1


def test_render_cli_returns_string():
    from decisions import Choice, make_decision, render_cli

    dp = make_decision(
        code="material.unspecified_defaulted",
        stage="planner",
        severity="assumption",
        context={"resolved": "worn_oak"},
        choices=(Choice(label="oak", plain="oak", apply={"field": "material", "value": "worn_oak"}),),
    )
    assert isinstance(render_cli([dp]), str)


def test_render_cli_empty_list_is_safe():
    from decisions import render_cli
    # No decisions → still a string (empty or whitespace)
    assert isinstance(render_cli([]), str)


# ── Slice 11: ForgeResult.decisions dataclass wiring ────────────────


def test_forge_result_default_decisions_is_empty_list():
    """ForgeResult.decisions defaults to an empty list — runs anywhere,
    no blender dependency (lives here instead of test_runner.py to avoid
    the BLENDER pytestmark skipif on a pure dataclass test)."""
    from runner import ForgeResult
    from gate import GateResult

    result = ForgeResult(
        glb_path="/tmp/fake.glb",
        gate=GateResult(passed=True, reasons=()),
        registered=False,
    )
    assert result.decisions == [], (
        "explicit-spec forge() should leave decisions empty by default"
    )
    # repr=False should keep decisions out of __repr__ for log clarity
    repr_str = repr(result)
    assert "decisions" not in repr_str, (
        "decisions should be repr=False to keep logs compact"
    )


def test_forge_result_accepts_decisions_in_constructor():
    """The planner path populates ForgeResult(decisions=...) with the
    resolver's output."""
    from runner import ForgeResult
    from gate import GateResult
    from decisions import Choice, make_decision

    dp = make_decision(
        code="material.family_defaulted",
        stage="planner",
        severity="assumption",
        context={"family": "wood", "resolved": "worn_oak"},
        choices=(),
    )
    result = ForgeResult(
        glb_path="/tmp/fake.glb",
        gate=GateResult(passed=True, reasons=()),
        registered=False,
        decisions=[dp],
    )
    assert len(result.decisions) == 1
    assert result.decisions[0].code == "material.family_defaulted"
