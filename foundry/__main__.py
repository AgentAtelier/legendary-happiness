"""CLI: forge one asset.
    cd foundry && .venv/bin/python -m foundry <spec.json> <lexicon.json> <library_dir>
    OR  --request "a low wide coffee table" <lexicon.json> <library_dir>
    OR from repo root: PYTHONPATH=. foundry/.venv/bin/python -m foundry ...

Subcommands:
    publish <library_dir> <project_dir> <lexicon_path> [assets_subdir]
        Publish forged .glb assets into a Godot project.
    quest --request "<prompt>" --scene <name> [--model <name>] [--port <port>]
        Full prompt→scene entrypoint: behaviour-gen → compile_scene →
        scaffold disposable project → builds/<name>/.
"""

import sys
from pathlib import Path

# Ensure the foundry package directory is on sys.path so bare imports
# (from compiler import ...) work for both direct execution from foundry/
# and python -m foundry from the repo root.
_foundry_dir = str(Path(__file__).resolve().parent)
if _foundry_dir not in sys.path:
    sys.path.insert(0, _foundry_dir)

from decisions import render_cli as _render_decisions_cli
from runner import forge, forge_from_request


def main() -> int:
    # -- subcommand routing
    if len(sys.argv) >= 2 and sys.argv[1] == "publish":
        from publish import _main as publish_main
        # Shift argv so publish._main sees only its own args
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        return publish_main()

    if len(sys.argv) >= 2 and sys.argv[1] == "quest":
        return _cmd_quest(sys.argv[2:])

    if "--request" in sys.argv:
        # --request "<text>" <lexicon.json> <library_dir>
        try:
            req_idx = sys.argv.index("--request")
            request_text = sys.argv[req_idx + 1]
            lexicon = sys.argv[req_idx + 2]
            lib_dir = sys.argv[req_idx + 3]
        except IndexError:
            print("usage: python -m foundry --request \"<text>\" <lexicon.json> <library_dir>")
            return 2

        result = forge_from_request(request_text, lexicon, lib_dir)
        status = "PASS" if result.gate.passed else "FAIL"
        print(f"[{status}] {result.glb_path}  registered={result.registered}")
        for reason in result.gate.reasons:
            print(f"  - {reason}")
        # Surface any Decision Points the material resolver emitted
        # (multi-member family, no material keyword, ambiguity).
        # render_cli suppresses `info` decisions and is a no-op for [].
        rendered = _render_decisions_cli(result.decisions)
        if rendered.strip():
            print(rendered)
        return 0 if result.gate.passed else 1

    if len(sys.argv) != 4:
        print("usage: python -m foundry <spec.json> <lexicon.json> <library_dir>")
        print("       python -m foundry --request \"<text>\" <lexicon.json> <library_dir>")
        print("       python -m foundry publish <library_dir> <project_dir> <lexicon_path>")
        return 2
    result = forge(sys.argv[1], sys.argv[2], sys.argv[3])
    status = "PASS" if result.gate.passed else "FAIL"
    print(f"[{status}] {result.glb_path}  registered={result.registered}")
    for reason in result.gate.reasons:
        print(f"  - {reason}")
    return 0 if result.gate.passed else 1


def _cmd_quest(args: list[str]) -> int:
    """Handle ``quest`` subcommand.

    Usage::
        python -m foundry quest --request "<prompt>" --scene <name>
            [--model <name>] [--port <port>]
            [--lexicon <path>]
            [--library-dir <path>]

    Runs the full prompt→scene path:
        1. QuestBehaviourPlanner generates a quest spec from the prompt
           + a default placed-entity manifest.
        2. scaffold_project copies the template, compiles the scene,
           copies assets, pre-imports → builds/<name>/.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m foundry quest",
        description="Generate a playable fetch-quest scene from a room prompt.",
    )
    parser.add_argument(
        "--request", required=True,
        help="Room prompt (e.g. 'a hermit's shack with worn furniture')"
    )
    parser.add_argument(
        "--scene", required=True,
        help="Output scene name (scaffolded under builds/<name>/)"
    )
    parser.add_argument(
        "--model", default=None,
        help="LLM model name for the behaviour-gen call (default: from env)"
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="LLM server port (default: 8002)"
    )
    parser.add_argument(
        "--lexicon",
        default="engine/devforge/spatial/asset_lexicon.json",
        help="Path to asset lexicon JSON"
    )
    parser.add_argument(
        "--library-dir",
        default="/home/mrg/dev/games/rpg/assets",
        help="Directory containing forged GLBs + their families"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible room generation"
    )
    parser.add_argument(
        "--camera", default="first", choices=["first", "third"],
        help="Camera mode: first-person or third-person (default: first)"
    )
    parser.add_argument(
        "--npc-count", type=int, default=2,
        help="Number of NPCs to generate quests for (default: 2)"
    )
    parsed = parser.parse_args(args)

    # ── Build the LLM ─────────────────────────────────────────
    from llm import FoundryLLM
    llm_kwargs: dict = {}
    if parsed.model:
        llm_kwargs["model"] = parsed.model
    if parsed.port:
        llm_kwargs["port"] = parsed.port
    if parsed.seed is not None:
        llm_kwargs["seed"] = parsed.seed
    llm = FoundryLLM(**llm_kwargs)

    # ── Step 0: Plan the room from the prompt (#6) ────────────
    from room_planner import RoomPlanner
    from room_layout import layout_room
    from asset_ensure import ensure_assets

    print(f"[quest] Planning room for: {parsed.request!r}")
    seed = parsed.seed
    if seed is not None:
        print(f"[quest] Seed: {seed}")
    # T-1: retry-once parse-failure fallback
    room_plan, room_decisions = _plan_room_with_fallback(
        parsed.request, llm, seed
    )
    npc_count = parsed.npc_count
    # C-0: apply theme-based control rules + global guards
    # EB-7: pass npc_count so the multi-NPC carryable guard fires
    from room_control import apply_rules
    room_plan, control_decisions = apply_rules(room_plan, parsed.request,
                                                npc_count=npc_count)
    room_decisions.extend(control_decisions)
    manifest, room_size, layout_decisions = layout_room(room_plan, seed=seed,
                                                         npc_count=npc_count)
    print(f"[quest] Room: {room_size['w']}x{room_size['d']} m, "
          f"{len(manifest)} entities")

    # Build any (category, material) the room needs that isn't in the library.
    ensure_decisions = ensure_assets(manifest, parsed.library_dir, parsed.lexicon)

    # ── Step 1: Behaviour-gen ─────────────────────────────────
    # C-4: Generate quests for multiple NPCs in a single LLM call.
    from behaviour_gen import QuestBehaviourPlanner
    planner = QuestBehaviourPlanner()

    # Carryables are the eligible quest targets.
    carryable_ids = {e["id"] for e in manifest if e.get("category") in (
        "key", "book", "cup", "gem", "bottle", "scroll", "coin-pouch",
        "candle", "dagger", "ring",
    )}
    print(f"[quest] Planning quests for {npc_count} NPCs: {parsed.request!r}")
    specs, quest_decisions = planner.plan_multi(
        parsed.request, manifest, llm,
        npc_count=npc_count, seed=seed,
        carryable_ids=carryable_ids,
    )
    decisions = room_decisions + layout_decisions + ensure_decisions + quest_decisions

    for spec in specs:
        target = spec.get("target_entity", "?")
        npc_role = spec.get("npc_role", "villager")
        npc_id = spec.get("npc_id", "?")
        print(f"[quest] {npc_id} ({npc_role}): target={target}")
        dialogue = spec.get("dialogue", {})
        for key in ("greet", "ask"):
            print(f"  {key}: {dialogue.get(key, '')}")

    # ── Step 2: Compile scene into scaffolded project ──────────
    # P-G: pass the theme to scene_compiler for per-theme lighting.
    from scaffold import scaffold_project
    from pathlib import Path as _Path2
    from room_control import _match_theme
    theme_row = _match_theme(parsed.request)
    room_theme = theme_row.get("theme", "*")
    template_dir = str(_Path2(__file__).resolve().parent / "godot_template")
    build_path = scaffold_project(
        name=parsed.scene,
        quest_specs=specs,
        manifest=manifest,
        template_dir=template_dir,
        library_dir=parsed.library_dir,
        out_root=str(_Path2.cwd() / "builds"),
        room_size=room_size,
        theme=room_theme,
        camera_mode=parsed.camera,
    )
    print(f"[quest] Build scaffolded: {build_path}")

    # Show quest data path
    data_path = str(build_path / "scenes" / "main_quest_data.json")
    print(f"[quest] Quest data: {data_path}")

    # ── Surface any Decision Points ───────────────────────────
    rendered = _render_decisions_cli(decisions)
    if rendered.strip():
        print(rendered)

    print(f"[quest] Done. Launch: godot --path {build_path}")
    return 0


def _plan_room_with_fallback(
    request: str, llm, seed: int | None
) -> tuple:
    """T-1: Plan a room with retry-once + minimal-default fallback.

    If the RoomPlanner's LLM output is unparseable, retry once.
    If that also fails, return a minimal default room plan + a
    Decision Point so the quest never crashes on junk output.
    """
    from room_planner import RoomPlanner
    from decisions import make_decision, Choice

    planner = RoomPlanner()

    try:
        return planner.plan(request, llm, seed=seed)
    except ValueError as e:
        print(f"[quest] RoomPlanner parse failure: {e}")
        # T-1: Fall back to minimal default room plan
        decisions = [
            make_decision(
                code="room.planner_parse_fallback",
                stage="room", severity="error",
                context={"error": str(e)[:200]},
                choices=(
                    Choice(label="Use default room",
                           plain="Fall back to a minimal default room",
                           apply={"field": "room"}),
                    Choice(label="Retry",
                           plain="Retry the RoomPlanner call",
                           apply={"action": "retry"}),
                ),
            )
        ]
        default_plan = {
            "room_size": {"w": 6.0, "d": 6.0},
            "props": [
                {"category": "table", "material": "worn_oak", "count": 1},
                {"category": "chair", "material": "worn_oak", "count": 1},
                {"category": "shelf", "material": "worn_oak", "count": 1},
            ],
        }
        print("[quest] Falling back to default room plan")
        return default_plan, decisions




sys.exit(main())
