"""System graph viewer feature.

NOTE: This module is parked under simulation/preview/, which is not
wired into the live pipeline.  The ``PreviewFeature`` base class and
``GraphViewer`` dependency do not exist in the current tree.  When
this feature is revived, restore the imports and wire it into the
preview controller.
"""

# from .base_feature import PreviewFeature
# from devforge.simulation.preview.graph_viewer import GraphViewer
# from devforge.simulation.preview.feature.base_feature import PreviewFeature


# class GraphViewFeature(PreviewFeature):
#
#     name = "graph_view"
#
#     def __init__(self):
#
#         self.viewer = GraphViewer()
#
#     # ---------------------------------------------------------
#
#     def run(self, controller, **kwargs):
#
#         graph = controller.system_graph()
#
#         return self.viewer.build(graph)