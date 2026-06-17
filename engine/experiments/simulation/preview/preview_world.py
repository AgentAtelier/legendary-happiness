from .preview_scene import PreviewScene


class PreviewWorld:
    def __init__(self):
        self.scenes = {}

    def get_scene(self, name: str):

        if name not in self.scenes:
            self.scenes[name] = PreviewScene()

        return self.scenes[name]

    def apply_operations(self, scene_name: str, operations):

        scene = self.get_scene(scene_name)

        for op in operations:
            t = op.get("type")

            if t == "add_node":
                scene.add_node(
                    op["parent"],
                    op["name"],
                    op["node_type"],
                )

            elif t == "remove_node":
                scene.remove_node(op["path"])

            elif t == "attach_script":
                scene.attach_script(op["node"], op["script"])

            elif t == "set_property":
                scene.set_property(op["node"], op["key"], op["value"])

            elif t == "add_resource":
                pass

            else:
                raise RuntimeError(f"Unknown operation: {t}")

        return scene
