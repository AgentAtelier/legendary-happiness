"""DevForge Health Check — verifies all modules load correctly.

Run with::

    python -m devforge.health_check

Imports are lazy — this module does nothing at import time.
"""

import sys
import importlib
import pkgutil


def run() -> int:
    """Run the health check and return exit code (0 = all OK, 1 = errors)."""
    print("\n" + "=" * 50)
    print("DEVFORGE YEAR 1 — HEALTH CHECK")
    print("=" * 50 + "\n")

    errors = []

    # ── Check all modules import ──
    print("Checking module imports...\n")

    import devforge

    for mod in pkgutil.walk_packages(devforge.__path__, devforge.__name__ + "."):
        try:
            importlib.import_module(mod.name)
            print(f"  OK  {mod.name}")
        except Exception as e:
            errors.append((mod.name, str(e)))
            print(f"  FAIL {mod.name}: {e}")

    print()

    # ── Check server loads ──
    print("Checking server module...")
    try:
        import devforge.platform.server.server

        print("  OK  Server module loads\n")
    except Exception as e:
        errors.append(("server", str(e)))
        print(f"  FAIL Server: {e}\n")

    # ── Check LLM router ──
    print("Checking LLM router...")
    try:
        from devforge.infrastructure.llm.router import LLMRouter

        router = LLMRouter()
        router.configure_mock()
        router.generate("test")
        print("  OK  Mock LLM works\n")
    except Exception as e:
        errors.append(("llm_router", str(e)))
        print(f"  FAIL LLM router: {e}\n")

    # ── Check pipeline ──
    print("Checking pipeline components...")
    try:
        import devforge.compilation.pipeline.architecture_planner
        import devforge.compilation.pipeline.architecture_compiler
        import devforge.compilation.pipeline.validator
        import devforge.compilation.pipeline.completeness
        import devforge.compilation.pipeline.repair_engine
        import devforge.compilation.pipeline.context_assembler
        import devforge.compilation.pipeline.operation_generator

        print("  OK  All pipeline components load\n")
    except Exception as e:
        errors.append(("pipeline", str(e)))
        print(f"  FAIL Pipeline: {e}\n")

    # ── Final Report ──
    print("=" * 50)
    if errors:
        print(f"HEALTH: ISSUES FOUND ({len(errors)} errors)")
        for name, err in errors:
            print(f"  - {name}: {err}")
    else:
        print("HEALTH: ALL OK")
    print("=" * 50 + "\n")

    if errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
