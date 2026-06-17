"""Feature registry for Preview Lab capabilities."""

from __future__ import annotations

from typing import Dict


class FeatureRegistry:

    def __init__(self):

        self._features: Dict[str, object] = {}

    # ---------------------------------------------------------

    def register(self, feature):

        name = feature.name

        self._features[name] = feature

    # ---------------------------------------------------------

    def run(self, name, controller, **kwargs):

        if name not in self._features:
            raise ValueError(f"Unknown feature: {name}")

        feature = self._features[name]

        return feature.run(controller, **kwargs)

    # ---------------------------------------------------------

    def list_features(self):

        return list(self._features.keys())