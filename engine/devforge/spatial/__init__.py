"""DevForge Spatial — LLM-driven scene layout from semantic intent.

The LLM is a topologist, not a geometer. It never outputs a Vector3.
It outputs semantic intent (pattern choice, slot→asset assignments, relative
anchors). Deterministic Python engines resolve those into absolute transforms
and emit standard batch_execute operations.

Architecture:
  lexicon.py         — AssetLexicon: load/validate asset_lexicon.json
  anchors.py         — AnchorResolver: ARCS → absolute Vector3
  compiler.py        — SpatialCompiler: layout JSON → DevForgePlan → ops
  layout_planner.py  — LayoutPlanner: LLM call with GBNF grammar
  bsp.py             — BSPPartitioner: multi-room buildings from split trees
  scatter.py         — ScatterEngine: Poisson-disk outdoor scatter placement
  ssp.py             — SSPEngine: semantic room archetypes + Intent Descriptor
  wfc.py             — WFCEngine: Wave Function Collapse dungeon generation
  room_intent_planner.py — RoomIntentPlanner: Intent Descriptor authoring
  patterns/          — *.yaml room topologies with ARCS slots
  prompts/           — *.gbnf grammars for LLM output constraint
"""

from devforge.spatial.anchors import AnchorResolver
from devforge.spatial.bsp import BSPPartitioner
from devforge.spatial.building_planner import BuildingPlanner
from devforge.spatial.compiler import SpatialCompiler
from devforge.spatial.layout_planner import LayoutPlanner
from devforge.spatial.lexicon import AssetLexicon
from devforge.spatial.room_intent_planner import RoomIntentPlanner
from devforge.spatial.scatter import ScatterEngine
from devforge.spatial.scatter_planner import ScatterPlanner
from devforge.spatial.ssp import SSPEngine
from devforge.spatial.ssp_planner import SSPPlanner
from devforge.spatial.voronoi import VoronoiEngine
from devforge.spatial.voronoi_planner import VoronoiPlanner
from devforge.spatial.wfc import WFCEngine
from devforge.spatial.wfc_planner import WFCPlanner

__all__ = [
    "AssetLexicon",
    "AnchorResolver",
    "SpatialCompiler",
    "LayoutPlanner",
    "BuildingPlanner",
    "BSPPartitioner",
    "ScatterEngine",
    "ScatterPlanner",
    "SSPEngine",
    "SSPPlanner",
    "WFCEngine",
    "WFCPlanner",
    "VoronoiEngine",
    "VoronoiPlanner",
    "RoomIntentPlanner",
]
