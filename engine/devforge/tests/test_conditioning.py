from devforge.reasoning.prompts.conditioning import (
    CONDITIONING_BLOCK,
    prepend_conditioning,
)


def test_prepend_when_enabled():
    out = prepend_conditioning("a forest village", enabled=True)
    assert out.startswith(CONDITIONING_BLOCK)
    assert out.endswith("a forest village")


def test_noop_when_disabled():
    assert prepend_conditioning("a forest village", enabled=False) == "a forest village"


def test_env_toggle_default_on(monkeypatch):
    monkeypatch.delenv("DEVFORGE_PLANNER_CONDITIONING", raising=False)
    assert prepend_conditioning("x").startswith(CONDITIONING_BLOCK)


def test_env_toggle_off(monkeypatch):
    monkeypatch.setenv("DEVFORGE_PLANNER_CONDITIONING", "0")
    assert prepend_conditioning("x") == "x"
