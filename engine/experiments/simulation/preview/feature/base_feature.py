"""Base class for preview features."""


class PreviewFeature:
    name = "base"

    def run(self, controller, **kwargs):
        raise NotImplementedError
