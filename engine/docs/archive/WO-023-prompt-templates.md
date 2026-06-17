<!-- ARCHIVED — see ~/dev/games/Forge/FORGE-STACK.md for current documentation -->

# WO-023 — Configurable LLM prompt template (Gemma / ChatML / raw)

**Read `00-EXECUTOR-BRIEFING.md` first — especially rules 10–12.**
**Executor:** DeepSeek. **Est. effort:** 3–5h.
**Goal:** DevForge's planner currently hard-codes the Gemma chat template
in `llama_client.py` (`_apply_gemma_template`). The user now switches
models (e.g. `Qwen3-14B-Q6_K.gguf`, which speaks ChatML) via a `stack
model` command — DevForge must follow via config instead of degrading
silently. No behavior change for the default (Gemma) path.

## Deliverables

1. Template registry + selection in `devforge/infrastructure/llm/llama_client.py`
2. New config `llm_prompt_template` in `devforge/infrastructure/runtime_config.py`
3. Pass-through in `router.configure_llama(...)` and BOTH entry points
   (`platform/mcp_server.py`, `platform/server/server.py`)
4. Warn-only mismatch check in `devforge/doctor.py`
5. Test suite `devforge/tests/test_prompt_templates.py` (≥ 10 tests),
   registered in `scripts/run_all_tests.sh`

## 1. Template registry (`llama_client.py`)

Replace the hardcoded `_apply_gemma_template` with a module-level registry.
Exact wire formats (do not improvise the control tokens):

```python
PROMPT_TEMPLATES: dict[str, dict] = {
    # Gemma has no system role — chat() folds system text into the user turn
    "gemma": {
        "user_wrap": "<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n",
        "system_wrap": None,   # fold into user turn as "[Instructions]\n{system}\n\n"
    },
    # ChatML (Qwen3, and most Qwen/Yi/InternLM family models)
    "chatml": {
        "user_wrap": "<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
        "system_wrap": "<|im_start|>system\n{system}<|im_end|>\n",
    },
    # No wrapping — for endpoints that template server-side
    "raw": {
        "user_wrap": "{prompt}",
        "system_wrap": None,
    },
}
```

- `LlamaClient.__init__(..., prompt_template: str = "gemma")` — unknown
  name → raise `ValueError` listing valid names (config validation will
  normally catch this first; the client must still defend itself).
- `generate()` wraps via the active template (replaces the
  `_apply_gemma_template` call). Keep a `_wrap(prompt)` helper.
- `chat(messages)` per template: if `system_wrap` is None, fold system
  content into the user turn exactly as the current Gemma code does;
  otherwise emit `system_wrap` before the wrapped user turn.
- Keep `_apply_gemma_template` as a deprecated thin alias calling the
  registry (one existing caller may remain; check with grep).
- Note in a comment: Qwen3 may emit `<think>...</think>` blocks —
  `ArchitecturePlanner._parse_response` already strips them; do NOT add
  a second stripping layer.

## 2. Config (`runtime_config.py`)

- Field: `llm_prompt_template: str = "gemma"`
- Env: `DEVFORGE_PROMPT_TEMPLATE` in `from_env()`
- Validation: add `VALID_PROMPT_TEMPLATES = {"gemma", "chatml", "raw"}`
  and a `validate()` entry mirroring the `llm_backend` check.

## 3. Wiring

- `router.configure_llama(...)` gains `prompt_template: str = "gemma"`,
  passes to `LlamaClient`.
- Both entry points pass `prompt_template=config.llm_prompt_template`
  (find the existing `configure_llama(` call sites; mirror how
  `timeout_s` was added in Round 8).

## 4. Doctor check (`doctor.py`)

In `check_llama`, after reading `/props`: if the model alias contains
`qwen|chatml`-family hints while the configured template is `gemma`
(or alias contains `gemma` while template is `chatml`), emit a **WARN**
(never FAIL): "model alias 'X' vs prompt template 'Y' — set
DEVFORGE_PROMPT_TEMPLATE". Keep the heuristic to a small table, not
cleverness.

## 5. Tests (`devforge/tests/test_prompt_templates.py`)

Standalone-script pattern (copy header/runner from
`test_context_clamp.py`). No live server: capture the wire payload by
monkeypatching `requests.post` (see how `test_godot_ai_mcp.py` pins wire
shapes — same philosophy, this suite pins the PROMPT bytes). Minimum:

1. gemma `generate("hi")` → payload prompt is exactly
   `<start_of_turn>user\nhi<end_of_turn>\n<start_of_turn>model\n`
2. chatml `generate("hi")` → exact ChatML bytes incl. trailing
   `<|im_start|>assistant\n`
3. raw `generate("hi")` → prompt == "hi"
4. gemma `chat()` with system folds `[Instructions]` into the user turn
   (byte-exact against current behavior — regression guard)
5. chatml `chat()` with system emits the system block BEFORE the user block
6. unknown template name → ValueError naming valid options
7. default is gemma when nothing configured
8. `RuntimeConfig.validate()` rejects `llm_prompt_template="qwen"` with a
   helpful message
9. `DEVFORGE_PROMPT_TEMPLATE=chatml` env round-trips through `from_env()`
10. `configure_llama(prompt_template="chatml")` reaches the client
    (assert on the constructed `LlamaClient.prompt_template`)

## Acceptance checklist

- [ ] `.venv/bin/python devforge/tests/test_prompt_templates.py` → all pass
- [ ] `scripts/run_all_tests.sh` → "All test suites passed." (suite registered)
- [ ] Default-path regression: gemma wire bytes byte-identical to before
      (test 1 + 4 prove it)
- [ ] grep shows no remaining direct `_apply_gemma_template` callers
      outside the alias itself
- [ ] WORKLOG.md entry appended (template at top of that file)

## Out of scope (architect handles after handback)

- `stack model` setting `DEVFORGE_PROMPT_TEMPLATE` automatically (dotfiles side)
- TUNING.md / CLAUDE.md documentation updates
- Sampler-profile tuning per model family
