"""Forge Testbench — unified testing chassis.

One runner, one result shape, self-describing metrics. Test content is
preserved; only the plumbing is rebuilt.

Usage:
  from forge_testbench import Test, Metric, Result, Runner, Catalog, matrix, scorecards

  # Register a test
  class MyTest(Test):
      id = "probe.my_thing"
      category = "probe"
      title = "My Thing"
      description = "Checks something."
      async def run(self, ctx):
          return {"ok": True}
      def score(self, raw):
          return ScoredResult(
              test_id=self.id,
              status="ok",
              score=100,
              metrics={"check": Metric(1, "bool", True, "passed")}
          )
"""

from .artifact import Artifact
from .catalog import CATALOG, catalog_entries, get_suites, register
from .context import Context
from .metric import Metric
from .reporting import matrix, scorecards, summary
from .result import Result, ScoredResult
from .runner import Runner, run
from .test import Test

# Import test modules to trigger @register decorators.
# Each category gets its own module; add new ones here as they migrate.
from .tests import probes  # noqa: F401 — triggers registration
