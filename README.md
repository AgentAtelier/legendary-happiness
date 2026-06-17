# Forge

A local, self-hosted toolchain that turns natural-language prompts into Godot
game scenes. You direct it iteratively: write a prompt, see the result, refine
with the next prompt — not one giant prompt that fills every gap.

## The parts
| Folder / service | What it is |
|---|---|
| `hub/` | FastAPI **ops panel** (127.0.0.1:8003) — orchestrates the stack, runs tests |
| `engine/` | The generation **engine** (DevForge): prompt → plan → compile → execute |
| llama.cpp | Local **LLM server** (127.0.0.1:8002), managed via `stack` + `stack.env` |
| Godot | The **game project** — lives outside this repo at `~/dev/games/rpg` |
| `legacy/` | Frozen archive (git-ignored, kept on disk) |

Config is the single source of truth in `~/.config/forge-stack/stack.env`.

## Start here
- **[docs/INDEX.md](docs/INDEX.md)** — the documentation map and current state.
- `docs/current/` — what's true now. `docs/archive/` — history.
- `docs/decisions/` — why key choices were made (ADRs).

## Running it
The stack runs as user services (`forge-hub`, llama, the DevForge MCP). Open the
ops panel at <http://127.0.0.1:8003>.
