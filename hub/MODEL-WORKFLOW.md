# Per-task model workflow

The chain shares ONE llama server (`:8002`) = one loaded model. The two
consumers want different things, so swap per task:

| Task | Model | Why |
|------|-------|-----|
| **Creative writing / chat** (default) | **Cydonia-Redux-22B** (`merged-22b-q4-k-m`) | Best prose; temp ~1.0. Poor/flaky for agent tools + DevForge planning (Mistral, no native tool-calls, slow under grammar). |
| **Building in Godot** (DevForge / agent) | **qwen3-14b** (`qwen3-14b-q6-k`) | Reliable grammar-constrained planning (3/3 entities, ~3× faster), native tool calls, 32k context. Set persona temp 0.2. |

## Swap

In the hub Models tab, or:

```sh
forge-model apply qwen3   &&  stack restart llama   # → building
forge-model apply cydonia &&  stack restart llama   # → writing
```

`forge-model apply` also sets the matching `DEVFORGE_PROMPT_TEMPLATE`
(both happen to be `chatml`). For agent/tool use also drop the persona
temperature to 0.2 (Character tab); for prose keep ~1.0.

## How the probes flag a mismatch

Run **Bench → Deep Probe** (or `python bench.py --probe`). On the wrong
model you'll see:

- `llama.tools` **broken** — model emits no native tool call (Cydonia).
- `devforge.plan` **degraded** — "planned … but SLOW (…s) — swap to qwen3".
- `odysseus.persona` **degraded** — temp too high for tool calls.

All green on `llama` + `devforge` ⇒ the loaded model is fit for building.

## Notes / known items

- **Odysseus tool retrieval** indexes MCP tools (apply_spec, godot-ai) into
  its Chroma collection only on the **first agent chat after a (re)start**.
  Until then `odysseus.retrieval` reports "index not warm" — run one chat
  turn to populate it. The custom embedding lane is on a FastEmbed fallback
  (the configured embedding endpoint URL is missing its `http://` prefix —
  fix in Odysseus settings if you want the richer lane).
- **`runtime.launch`** often reads FPS 0 even when the game launches — an
  editor monitor-capture quirk, not a real failure (verdict: degraded).
