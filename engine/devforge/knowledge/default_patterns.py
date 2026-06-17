from devforge.knowledge.pattern_library import PatternLibrary


def load_default_patterns() -> PatternLibrary:

    library = PatternLibrary()

    # ─────────────────────────
    # Player Controller
    # ─────────────────────────

    library.register(
        "player_controller",
        {
            "entities": ["Player"],
            "systems": [
                "Movement",
                "CameraFollow",
            ],
            "signals": [],
        },
    )

    # ─────────────────────────
    # Health System
    # ─────────────────────────

    library.register(
        "health_system",
        {
            "entities": ["Player", "Enemy"],
            "systems": [
                "Health",
                "Damage",
            ],
            "signals": [
                {
                    "name": "health_changed",
                    "source": "Health",
                    "target": "HUD",
                }
            ],
        },
    )

    # ─────────────────────────
    # Enemy AI
    # ─────────────────────────

    library.register(
        "enemy_ai",
        {
            "entities": ["Enemy"],
            "systems": [
                "EnemyAI",
                "Navigation",
            ],
            "signals": [],
        },
    )

    return library