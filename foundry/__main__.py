"""CLI: forge one asset.
    cd foundry && .venv/bin/python -m foundry <spec.json> <lexicon.json> <library_dir>
    OR from repo root: PYTHONPATH=. foundry/.venv/bin/python -m foundry ...
"""

import sys
from pathlib import Path

# Ensure the foundry package directory is on sys.path so bare imports
# (from compiler import ...) work for both direct execution from foundry/
# and python -m foundry from the repo root.
_foundry_dir = str(Path(__file__).resolve().parent)
if _foundry_dir not in sys.path:
    sys.path.insert(0, _foundry_dir)

from runner import forge


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: python -m foundry <spec.json> <lexicon.json> <library_dir>")
        return 2
    result = forge(sys.argv[1], sys.argv[2], sys.argv[3])
    status = "PASS" if result.gate.passed else "FAIL"
    print(f"[{status}] {result.glb_path}  registered={result.registered}")
    for reason in result.gate.reasons:
        print(f"  - {reason}")
    return 0 if result.gate.passed else 1


sys.exit(main())
