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
    parsed = parser.parse_args(args)

    # ── Default manifest (shared across all quest prompts) ────
    manifest = [
        {"id": "table_0", "category": "table", "material": "worn_oak",
         "wear": 0.5, "x": 1.5, "y": 0.0, "z": -2.0},
        {"id": "shelf_0", "category": "shelf", "material": "rough_granite",
         "wear": 0.3, "x": -2.0, "y": 0.0, "z": -3.0},
        {"id": "cabinet_0", "category": "cabinet", "material": "wrought_iron",
         "wear": 0.7, "x": 2.5, "y": 0.0, "z": -1.5},
        {"id": "table_1", "category": "table", "material": "worn_oak",
         "wear": 0.2, "x": -1.0, "y": 0.0, "z": -1.0},
    ]

    # ── Build the LLM ─────────────────────────────────────────
    from llm import FoundryLLM
    llm_kwargs = {}
    if parsed.model:
        llm_kwargs["model"] = parsed.model
    if parsed.port:
        llm_kwargs["port"] = parsed.port
    llm = FoundryLLM(**llm_kwargs)

    # ── Step 1: Behaviour-gen ─────────────────────────────────
    from behaviour_gen import QuestBehaviourPlanner
    planner = QuestBehaviourPlanner()

    print(f"[quest] Planning quest for: {parsed.request!r}")
    spec, decisions = planner.plan(parsed.request, manifest, llm)

    target = spec.get("target_entity", "?")
    npc_role = spec.get("npc_role", "villager")
    print(f"[quest] NPC role: {npc_role}")
    print(f"[quest] Target entity: {target}")
    print(f"[quest] Dialogue:")
    dialogue = spec.get("dialogue", {})
    for key in ("greet", "ask", "wrong", "thank"):
        print(f"  {key}: {dialogue.get(key, '')}")

    # ── Step 2: Compile scene into scaffolded project ──────────
    from scaffold import scaffold_project
    from pathlib import Path as _Path2
    template_dir = str(_Path2(__file__).resolve().parent / "godot_template")
    build_path = scaffold_project(
        name=parsed.scene,
        quest_spec=spec,
        manifest=manifest,
        template_dir=template_dir,
        library_dir=parsed.library_dir,
        out_root=str(_Path2.cwd() / "builds"),
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


sys.exit(main())
