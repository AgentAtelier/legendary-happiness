# TUNING.md — Getting the Most Out of DevForge on This Machine

Hardware baseline: **RX 6800 (16 GB, RDNA2/gfx1030, ROCm with
`HSA_OVERRIDE_GFX_VERSION=10.3.0`)** running llama.cpp with
**Gemma 4 26B-A4B (MoE, ~4B active) Q4_K_XL**, `--ctx-size 12288`,
`--parallel 1`, flash-attn, q4_0 KV cache, `--no-warmup`.

The guiding principle is a tailor's: *cut your coat according to your
cloth*. The pipeline now measures the cloth — `python -m devforge.doctor
--warm` reports the real numbers below for your running server; re-run it
after every llama-server flag change instead of trusting this file.

---

## 1. The context window is the whole game (now automatic)

llama.cpp holds **prompt + generation in one window**. With
`--ctx-size 12288` and `DEVFORGE_LLAMA_MAX_TOKENS=4096`, only
`12288 − 4096 − 1024 (template overhead) = 7168` tokens remain for
assembled context. DevForge used to *assume* 24000 and the server
silently dropped the oldest tokens — which is the instruction prefix,
the worst possible loss.

Since Round 8 the MCP server queries `/props` at startup and
**auto-clamps the budget** (you'll see `Context budget clamped
24000 → 7168` in the log). Nothing to configure.

**Lever you control:** the planner's output is a small grammar-constrained
JSON delta — it never needs 4096 generated tokens. Halving it hands the
difference straight to context:

```bash
export DEVFORGE_LLAMA_MAX_TOKENS=2048   # context budget becomes 9216
```

Watch one session's logs for `Generation hit n_predict` warnings; none
means 2048 is safe.

## 2. Prompt-cache reuse is broken on this setup — measured, not guessed

`doctor --warm` sends the planner's static prefix twice and reads
llama.cpp's `timings.prompt_n`. Result on this machine (June 2026):

```
[WARN] Prompt-cache reuse — second call reprocessed 89/88 tokens
```

Every turn re-prefills the **entire** prompt. At ~7K context tokens and
RDNA2 prefill speeds that's seconds of pure waste per turn. The cause:
Gemma uses **sliding-window attention (SWA)**, and llama.cpp's default
SWA cache cannot restore a previous prefix — `cache_prompt: true` (which
DevForge sends) is silently ignored.

**Fix to try** (costs VRAM — the full-size KV cache for SWA layers):

```bash
llama-server ... --swa-full
```

Then re-run `python -m devforge.doctor --warm`. Success looks like
"second call reprocessed only ~1/88 tokens". DevForge's prompt is
already built static-prefix-first (instructions → schema → example →
context → request) precisely so this reuse pays off across turns —
mise en place: the stable ingredients are prepped once, up front.

If `--swa-full` doesn't fit in VRAM at 12288 ctx, it usually beats
raw context size: try `--swa-full --ctx-size 10240` and compare
turn latency. Check headroom with `rocm-smi --showmeminfo vram`.

## 3. Prefill speed: batch sizes

DevForge's workload is prefill-heavy (large prompt, small output).
`--batch-size 512 --ubatch-size 512` is conservative; prefill throughput
on RDNA2 usually rises with a larger ubatch if VRAM allows:

```bash
--batch-size 1024 --ubatch-size 1024   # measure, don't assume
```

Measure with the doctor's reported `prompt_ms` or llama-server's own
log line per request. Revert if VRAM pressure causes swapping.

## 4. KV cache quantization

`--cache-type-k q4_0 --cache-type-v q4_0` is the right call for fitting
12K+ context in 16 GB. If you free VRAM elsewhere (e.g. shorter ctx with
`--swa-full`), upgrading **V** to `q8_0` is the better spend than longer
context — V-cache quantization degrades output quality more than K.
Grammar-constrained JSON hides small degradation well, so this is a
"only if VRAM is free" tweak.

## 5. Warmup

`--no-warmup` makes llama-server start fast but the first request slow.
DevForge's grammar self-test at MCP-server startup already exercises the
model once; running `python -m devforge.doctor --warm` right after
starting llama-server does the same *and* primes the planner's static
prefix into the KV cache (a pilot's pre-flight checklist that also
de-ices the wings).

## 6. Things that are already right — leave them

| Flag / setting | Why it's correct |
|---|---|
| `--parallel 1` | DevForge serializes pipeline runs behind a lock; one slot = the whole window for each request. The doctor warns if slots > 1. |
| `--flash-attn on` | Required for V-cache quantization; faster prefill. |
| `-ngl 99` | Whole model on GPU; the MoE's ~4B active params is why 77 t/s decode is reachable on RDNA2. |
| `--alias gemma-26b` | Cosmetic, but the doctor and logs display it. |
| `seed: 0`, `cache_prompt: true` (DevForge-side) | Deterministic, cache-friendly requests. |
| DevForge sampler profiles (temp 0.2, top_k 40) | Low temperature is right for grammar-constrained JSON; per-request params override server defaults. |

## 7. Timeout

Worst case on this hardware ≈ full 7K prefill (no cache reuse) + 4K
generation at ~77 t/s ≈ 90–120 s. The old hardcoded 120 s client timeout
sat exactly on that edge; the default is now **300 s**, configurable:

```bash
export DEVFORGE_LLM_TIMEOUT=300
```

## 8. The measurement loop

After ANY change to llama-server flags:

```bash
python -m devforge.doctor --warm     # window math, cache reuse, prefill ms
python -m devforge.verify_pipeline   # pipeline still sound (mock LLM)
```

Treat it like dyno-tuning an engine: one change, one measurement,
keep or revert.
