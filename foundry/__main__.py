"""CLI: forge one asset.
    cd foundry && .venv/bin/python -m foundry <spec.json> <lexicon.json> <library_dir>
    OR  --request "a low wide coffee table" <lexicon.json> <library_dir>
    OR from repo root: PYTHONPATH=. foundry/.venv/bin/python -m foundry ...

Subcommands:
    publish <library_dir> <project_dir> <lexicon_path> [assets_subdir]
        Publish forged .glb assets into a Godot project.
"""

import sys
from pathlib import Path

# Ensure the foundry package directory is on sys.path so bare imports
# (from compiler import ...) work for both direct execution from foundry/
# and python -m foundry from the repo root.
_foundry_dir = str(Path(__file__).resolve().parent)
if _foundry_dir not in sys.path:
    sys.path.insert(0, _foundry_dir)

from runner import forge, forge_from_request


def main() -> int:
    # -- subcommand routing
    if len(sys.argv) >= 2 and sys.argv[1] == "publish":
        from publish import _main as publish_main
        # Shift argv so publish._main sees only its own args
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        return publish_main()

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


sys.exit(main())
