"""Import smoke test — every module under devforge. must import cleanly.

Run with: python devforge_project_tests/test_imports.py (or pytest).
"""

import os
import sys

# Ensure the repo root is importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pkgutil

import devforge


def test_all_modules_import():

    for mod in pkgutil.walk_packages(
        devforge.__path__,
        devforge.__name__ + "."
    ):
        __import__(mod.name)


if __name__ == "__main__":
    test_all_modules_import()
    print("PASS: all devforge modules imported")
