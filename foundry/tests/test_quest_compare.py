"""Tests for the multi-model quest comparison runner."""

from __future__ import annotations

import quest_compare

# ── Bug #1: the comparison table was blind to dialogue ──────────────
# `_run_quest` stripped each line and then matched a 2-space-indented
# prefix ("  greet:"), so after the strip the indent was gone and the
# dialogue was never captured.  Parsing is extracted into
# `_parse_quest_output` so it can be tested without a subprocess.

SAMPLE_QUEST_STDOUT = """\
[quest] Planning quest for: "a blacksmith's back room"
[quest] NPC role: blacksmith
[quest] Target entity: table_0
[quest] Dialogue:
  greet: Welcome to my forge, traveler. I am the blacksmith.
  ask: I need to retrieve a special hammer from the table. Could you fetch it?
  wrong: No, that is not the hammer I need.
  thank: Thank you! You have my gratitude, traveler.
[quest] Build scaffolded: /tmp/builds/blacksmith_qwen3-5-9b-q8-0
[quest] Done. Launch: godot --path /tmp/builds/blacksmith_qwen3-5-9b-q8-0
"""


def test_parse_quest_output_captures_role_and_target():
    spec = quest_compare._parse_quest_output(SAMPLE_QUEST_STDOUT)
    assert spec["npc_role"] == "blacksmith"
    assert spec["target"] == "table_0"


def test_parse_quest_output_captures_all_dialogue_lines():
    spec = quest_compare._parse_quest_output(SAMPLE_QUEST_STDOUT)
    assert spec["greet"] == "Welcome to my forge, traveler. I am the blacksmith."
    assert spec["ask"] == "I need to retrieve a special hammer from the table. Could you fetch it?"
    assert spec["wrong"] == "No, that is not the hammer I need."
    assert spec["thank"] == "Thank you! You have my gratitude, traveler."


# ── Bug #2: systemd start-limit blocked multi-swap runs ─────────────
# StartLimitBurst=3 / 2min means the 4th rapid restart is refused.
# `reset-failed` must run BEFORE every swap (it resets the start-limit
# counter), not only at restore time.

def test_reset_failed_runs_before_every_swap(monkeypatch):
    order: list[str] = []

    monkeypatch.setattr(quest_compare, "_get_current_model", lambda: "orig-model")
    monkeypatch.setattr(quest_compare, "_resolve_model_alias", lambda frag: frag)
    monkeypatch.setattr(
        quest_compare, "_check_model_fit", lambda alias: {"status": "fits"}
    )
    monkeypatch.setattr(
        quest_compare, "_reset_failed_llama", lambda: order.append("reset")
    )

    def fake_swap(fragment: str) -> bool:
        order.append("swap")
        return True

    monkeypatch.setattr(quest_compare, "_swap_model", fake_swap)
    monkeypatch.setattr(quest_compare, "_wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(
        quest_compare, "_run_quest", lambda prompt, scene, npc_count=2: (True, "", {})
    )

    rc = quest_compare.run_compare(
        prompt="a hermit's shack",
        fragments=["model-a", "model-b"],
        prefix="t",
    )

    assert rc == 0
    # Every swap must be immediately preceded by a reset.
    swap_indices = [i for i, x in enumerate(order) if x == "swap"]
    assert swap_indices, "expected at least one swap"
    for i in swap_indices:
        assert i > 0 and order[i - 1] == "reset", (
            f"swap at {i} not preceded by reset; order={order}"
        )
