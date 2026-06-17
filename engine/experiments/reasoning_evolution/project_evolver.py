class ProjectEvolver:

    def evolve(self, project_state):

        suggestions = []

        if "Enemy" in project_state:

            suggestions.append(
                "add_enemy_variants"
            )

        if "Player" in project_state:

            suggestions.append(
                "add_skill_tree"
            )

        return suggestions