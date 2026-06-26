"""World CLI — drive the World-DAG by hand (no LLM) and watch the op-log grow.

Subcommands over a world directory (persisted via world.persistence):
    add-space --dir D --id ID --size W H D [--origin X Y Z] [--theme T]
    add-portal --dir D --id ID --from A --to B --pos X Y Z --size W H
    add-entity --dir D --space S --id ID --type T --pos X Y Z
    move-entity --dir D --space S --id ID --pos X Y Z
    show --dir D
    replay --dir D

Uses ``apply_op_checked`` so invalid ops PRINT the Violation messages
and exit nonzero (never crash).  On success, ``save_world`` + one-line
summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the foundry package directory is on sys.path so bare imports
# from world.* work.
_foundry_dir = str(Path(__file__).resolve().parent)
if _foundry_dir not in sys.path:
    sys.path.insert(0, _foundry_dir)

from world.model import World
from world.operations import WorldOpError
from world.persistence import load_world, save_world
from world.validation import WorldValidationError, apply_op_checked


def _load_or_new(dir_path: str) -> World:
    """Load an existing world from ``dir_path``, or return an empty World
    if no op_log.json exists yet."""
    try:
        return load_world(dir_path)
    except FileNotFoundError:
        return World()


def _load_existing(dir_path: str) -> World:
    """Load an existing world; exit with an error if it doesn't exist."""
    try:
        return load_world(dir_path)
    except FileNotFoundError:
        print(f"Error: no world found at {dir_path!r}", file=sys.stderr)
        sys.exit(1)


def _build_op(args: argparse.Namespace) -> dict:
    """Build an op dict from parsed args; dispatches on subcommand."""
    cmd = args.subcommand  # set by the subparser dest

    if cmd == "add-space":
        op: dict = {
            "op": "add_space",
            "id": args.id,
            "brief": {},
            "footprint": {
                "origin": list(args.origin),
                "size": list(args.size),
            },
        }
        if args.theme:
            op["brief"]["theme"] = args.theme
        if args.seed is not None:
            op["seed"] = args.seed
        return op

    if cmd == "add-portal":
        return {
            "op": "add_portal",
            "id": args.id,
            "from_space": args.from_space,
            "to_space": args.to_space,
            "position": list(args.pos),
            "size": list(args.size),
        }

    if cmd == "add-entity":
        return {
            "op": "add_entity",
            "space": args.space,
            "entity": {
                "id": args.id,
                "type": args.type,
                "pos": list(args.pos),
            },
        }

    if cmd == "move-entity":
        return {
            "op": "move_entity",
            "space": args.space,
            "entity_id": args.id,
            "new_pos": list(args.pos),
        }

    raise SystemExit(f"Unknown subcommand: {cmd}")


def _apply_and_save(world: World, op: dict, dir_path: str) -> None:
    """Validate, apply, save.  Exits nonzero on any violation/referential
    error, printing the problem to stderr so the operator can correct."""
    try:
        world = apply_op_checked(world, op)
    except WorldValidationError as e:
        for v in e.violations:
            print(f"Violation [{v.code}]: {v.message}", file=sys.stderr)
        sys.exit(1)
    except WorldOpError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    save_world(world, dir_path)
    op_name = op["op"]
    print(
        f"Success: {op_name} applied. "
        f"World now has {len(world.nodes)} space(s) "
        f"and {len(world.portals)} portal(s)."
    )


def _cmd_add(args: argparse.Namespace) -> None:
    """Shared handler for add-space / add-portal / add-entity / move-entity."""
    world = _load_or_new(args.dir)
    op = _build_op(args)
    _apply_and_save(world, op, args.dir)


def _cmd_show(args: argparse.Namespace) -> None:
    """Print a formatted overview of the world.

    PROMPT 2-A: ``--json`` flag prints ``world.query.world_index(world)``
    as formatted JSON (LLM-consumable compact map) instead of the
    human-readable table.  Default (no flag) keeps the original
    formatted text for backwards-compatibility with the original
    per-op tests in ``test_world_cli.py``.
    """
    world = _load_existing(args.dir)

    if getattr(args, "json", False):
        # Local import keeps the top-of-module import surface lean
        # (world.query is only needed in JSON mode).
        from world.query import world_index
        print(json.dumps(world_index(world), indent=2, sort_keys=True))
        return

    print(f"World at {args.dir!r}:")
    print(f"  Spaces: {len(world.nodes)}")
    for sid in sorted(world.nodes):
        n = world.nodes[sid]
        fp = n.footprint
        origin = fp.get("origin", [])
        size = fp.get("size", [])
        theme = n.brief.get("theme", "") if n.brief else ""
        theme_str = f"  theme={theme}" if theme else ""
        print(
            f"    [{sid}] origin={origin} size={size}{theme_str}"
            f"  seed={n.seed}  entities={len(n.entities)}"
            f"  portals={n.portals}"
        )
        for e in n.entities:
            print(f"      entity id={e.id!r} type={e.type!r} pos={list(e.pos)}")

    print(f"  Portals: {len(world.portals)}")
    for pid in sorted(world.portals):
        p = world.portals[pid]
        print(
            f"    [{pid}] {p.from_space} <-> {p.to_space}"
            f"  pos={list(p.position)}  size={list(p.size)}"
        )

    print(f"  Op count: {len(world.op_log)}")


def _cmd_replay(args: argparse.Namespace) -> None:
    """Reload from op_log and confirm reconstruction."""
    world = _load_existing(args.dir)
    print(
        f"Reconstructed world successfully from {len(world.op_log)} op(s)."
        f"  Spaces: {len(world.nodes)}  Portals: {len(world.portals)}"
    )


# ── PROMPT 2-A: apply (batch from JSON patch file) ────────────────────


def _cmd_apply(args: argparse.Namespace) -> None:
    """PROMPT 2-A: ``apply`` reads a JSON-array patch file and applies
    each op via ``apply_op_checked``.  Saves the world ATOMICALLY —
    the on-disk state is only updated after the full batch succeeds.
    On any violation: print structured Violation(s) to stderr and exit
    nonzero WITHOUT saving (roll forward by never committing).
    """
    world = _load_existing(args.dir)
    patch_path = Path(args.patch)
    if not patch_path.exists():
        print(f"Error: patch file not found: {args.patch!r}", file=sys.stderr)
        sys.exit(1)
    try:
        patch_text = patch_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error: cannot read patch file {args.patch!r}: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        ops = json.loads(patch_text)
    except json.JSONDecodeError as e:
        print(f"Error: patch file {args.patch!r} is not valid JSON: {e}",
              file=sys.stderr)
        sys.exit(1)
    if not isinstance(ops, list):
        print(
            f"Error: patch file must contain a JSON ARRAY of ops, "
            f"got {type(ops).__name__}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        for op in ops:
            world = apply_op_checked(world, op)
    except WorldValidationError as e:
        for v in e.violations:
            print(f"Violation [{v.code}]: {v.message}", file=sys.stderr)
        sys.exit(1)
    except WorldOpError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # ATOMIC: only NOW, after the full batch succeeded, commit.
    save_world(world, args.dir)
    print(
        f"Applied {len(ops)} ops. "
        f"Spaces: {len(world.nodes)}. Portals: {len(world.portals)}."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="world-cli",
        description="Drive the World-DAG by hand — no LLM required.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # ── add-space ──────────────────────────────────────────────────
    p = sub.add_parser("add-space", help="Create a new space node")
    p.add_argument("--dir", required=True, help="World directory")
    p.add_argument("--id", required=True, help="Space id")
    p.add_argument(
        "--size", required=True, nargs=3, type=float,
        help="Width Height Depth (metres)",
    )
    p.add_argument(
        "--origin", nargs=3, type=float, default=[0.0, 0.0, 0.0],
        help="Origin X Y Z (default: 0 0 0)",
    )
    p.add_argument("--theme", default=None, help="Theme tag (stored in brief)")
    p.add_argument("--seed", type=int, default=None, help="Explicit seed (default: derived from id)")

    # ── add-portal ─────────────────────────────────────────────────
    p = sub.add_parser("add-portal", help="Create a portal between two spaces")
    p.add_argument("--dir", required=True, help="World directory")
    p.add_argument("--id", required=True, help="Portal id")
    p.add_argument(
        "--from", required=True, dest="from_space",
        help="Source space id",
    )
    p.add_argument(
        "--to", required=True, dest="to_space",
        help="Destination space id",
    )
    p.add_argument(
        "--pos", required=True, nargs=3, type=float,
        help="Portal position X Y Z",
    )
    p.add_argument(
        "--size", required=True, nargs=2, type=float,
        help="Portal width height",
    )

    # ── add-entity ─────────────────────────────────────────────────
    p = sub.add_parser("add-entity", help="Place an entity in a space")
    p.add_argument("--dir", required=True, help="World directory")
    p.add_argument("--space", required=True, help="Target space id")
    p.add_argument("--id", required=True, help="Entity id")
    p.add_argument("--type", required=True, help="Entity type")
    p.add_argument(
        "--pos", required=True, nargs=3, type=float,
        help="Entity position X Y Z",
    )

    # ── move-entity ────────────────────────────────────────────────
    p = sub.add_parser("move-entity", help="Move an entity to a new position")
    p.add_argument("--dir", required=True, help="World directory")
    p.add_argument("--space", required=True, help="Target space id")
    p.add_argument("--id", required=True, help="Entity id")
    p.add_argument(
        "--pos", required=True, nargs=3, type=float,
        help="New position X Y Z",
    )

    # ── show ───────────────────────────────────────────────────────
    p = sub.add_parser("show", help="Print spaces, portals, entities, op-count")
    p.add_argument("--dir", required=True, help="World directory")
    # PROMPT 2-A: --json prints world.query.world_index output (compact
    # LLM-consumable map).  Default stays the human-readable table for
    # backwards compatibility with the original per-op tests.
    p.add_argument(
        "--json", action="store_true",
        help="Print world.query.world_index output as JSON (LLM-consumable)",
    )

    # ── apply (PROMPT 2-A) ───────────────────────────────────────────
    p = sub.add_parser(
        "apply",
        help="Apply a JSON-array patch file (each op gated by apply_op_checked)",
    )
    p.add_argument("--dir", required=True, help="World directory")
    p.add_argument(
        "patch", help="Path to a JSON file containing an array of ops",
    )

    # ── replay ─────────────────────────────────────────────────────
    p = sub.add_parser("replay", help="Reload from op_log; confirm reconstruction")
    p.add_argument("--dir", required=True, help="World directory")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cmd = args.subcommand
    if cmd in ("show",):
        _cmd_show(args)
        return 0
    if cmd == "replay":
        _cmd_replay(args)
        return 0
    if cmd == "apply":
        # PROMPT 2-A: batch JSON-patch file applier.
        _cmd_apply(args)
        return 0
    # add-space, add-portal, add-entity, move-entity
    _cmd_add(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
