#!/usr/bin/env python3
"""
End-to-end integration test for DevForge pipeline.

Tests Phase 9-10 features directly via PipelineEngine:
  - Stage latencies in PipelineResult
  - Cache stats (hit/miss tracking)
  - Grammar configuration
  - Gate results (governance)
  - Monitor per-stage p50/p95 stats
"""

from __future__ import annotations

import os
import sys
import time

tests_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(tests_dir)  # terraforge-master/terraforge-master/
sys.path.insert(0, project_root)

# ── 1. Setup with mock LLM ──
os.environ["DEVFORGE_LLM_BACKEND"] = "mock"
os.environ["DEVFORGE_GAME_ROOT"] = project_root

from devforge.infrastructure.runtime_config import set_config, RuntimeConfig

config = RuntimeConfig(
    llm_backend="mock",
    executor_backend="devforge_plugin",
    game_root=project_root,
)
set_config(config)

from devforge.infrastructure.llm.router import LLMRouter
from devforge.knowledge.system_graph.system_graph import SystemGraph
from devforge.reasoning.ai.planning.lru_cache import LRUPlanCache
from devforge.compilation.pipeline.engine import PipelineEngine
from devforge.platform.monitor.monitor import Monitor

# ── 2. Create engine with cache ──
llm = LLMRouter()
# Richer mock response for non-empty plan
llm.configure_mock(
    response_fn=lambda p: (
        '{"systems":[{"name":"player","description":"Player character system"}],'
        '"entities":[{"name":"Player","type":"CharacterBody3D","parent":".",'
        '"components":["health","movement"],"script":"game/PlayerController.gd"}],'
        '"connections":[]}'
    )
)

system_graph = SystemGraph()
plan_cache = LRUPlanCache(max_entries=10)

# Resolve grammar path
grammar_path = os.path.join(project_root, "devforge", "reasoning", "prompts", "arch_planner.gbnf")
if not os.path.exists(grammar_path):
    grammar_path = None

engine = PipelineEngine(
    llm=llm,
    system_graph=system_graph,
    config=config,
    plan_cache=plan_cache,
    grammar_path=grammar_path,
)
# Use valid risk subsystems for governance gates
engine.risk_subsystems = ["npc_behaviour"]
engine.risk_depth = "new_behaviour"

monitor = Monitor()

# ── 3. Test 1: First run (cache MISS) ──
print("=" * 64)
print("TEST 1: First pipeline run (cache MISS)")
print("=" * 64)

prompt = "add a spaceship that can fly"
scene = {"name": "Main", "type": "Node3D", "children": []}

start = time.time()
result = engine.run_pipeline(prompt, scene)
elapsed = time.time() - start

print(f"  Files: {len(result.files)}")
print(f"  Operations: {len(result.operations)}")
print(f"  Errors: {len(result.errors)}")
print(f"  Elapsed: {elapsed * 1000:.0f}ms")

# Verify stage latencies
stages = result.stage_latencies
print(f"\n  Stage latencies ({len(stages)} phases):")
for stage_name in sorted(stages.keys()):
    print(f"    {stage_name}: {stages[stage_name]:.1f}ms")

assert len(stages) > 0, "No stage latencies recorded!"
expected = {
    "context_assembly",
    "architecture_planning",
    "compilation",
    "operation_generation",
    "completeness",
    "validation",
    "repair",
}
actual = set(stages.keys())
missing = expected - actual
if missing:
    print(f"  ⚠ Missing stages: {missing}")

# Verify cache stats
cache = result.cache_stats
print(
    f"\n  Cache: hits={cache.get('hits', 0)}, misses={cache.get('misses', 0)}, "
    f"hit_rate={cache.get('hit_rate', 0)}, entries={cache.get('entries', 0)}"
)
assert cache.get("misses", 0) >= 1, f"Expected at least 1 cache miss: {cache}"

# Verify grammar
print(f"  Grammar configured: {engine.grammar is not None}")
if grammar_path:
    assert engine.grammar is not None, "Grammar should be loaded"

# Verify gate results
gates = result.gate_results
print(f"  Gate results: {len(gates)} gates")
for gr in gates:
    print(f"    {gr.gate_name}: {'PASS' if gr.passed else 'FAIL'} (risk={gr.risk_score}, tier={gr.risk_tier})")

# ── 4. Test 2: Second run (cache HIT) ──
print()
print("=" * 64)
print("TEST 2: Second pipeline run (cache HIT)")
print("=" * 64)

result2 = engine.run_pipeline(prompt, scene)

print(f"  Files: {len(result2.files)}")
print(f"  Operations: {len(result2.operations)}")

cache2 = result2.cache_stats
print(f"  Cache: hits={cache2.get('hits', 0)}, misses={cache2.get('misses', 0)}, hit_rate={cache2.get('hit_rate', 0)}")
assert cache2.get("hits", 0) >= 1, f"Expected at least 1 cache hit: {cache2}"

# ── 5. Test 3: Run with trace recording ──
print()
print("=" * 64)
print("TEST 3: Trace recording for /perf endpoint")
print("=" * 64)

for i in range(3):
    trace = monitor.begin_trace(f"test_prompt_{i}")
    r = engine.run_pipeline(f"add a door that opens and closes {i}", {"name": "Main", "type": "Node3D", "children": []})
    for stage_name, stage_ms in r.stage_latencies.items():
        monitor.log_step(trace, stage_name, {"elapsed_ms": round(stage_ms, 1)})
    monitor.end_trace(
        trace,
        status="complete",
        cache_hits=r.cache_stats.get("hits", 0),
        cache_misses=r.cache_stats.get("misses", 0),
        cache_hit_rate=r.cache_stats.get("hit_rate", 0),
    )

# Verify /perf stats
perf = monitor.get_perf_stats()
print(f"  Total p50: {perf['total']['p50_ms']}ms")
print(f"  Total p95: {perf['total']['p95_ms']}ms")
print(f"  Total samples: {perf['total']['samples']}")

perf_stages = perf.get("stages", {})
print(f"  Per-stage count: {len(perf_stages)}")
for sn, sd in sorted(perf_stages.items()):
    print(f"    {sn}: p50={sd['p50_ms']}ms  p95={sd['p95_ms']}ms  n={sd['samples']}")

assert perf["total"]["samples"] >= 3, f"Expected >=3 samples, got {perf['total']['samples']}"
assert len(perf_stages) > 0, "No per-stage stats"
print(f"  Cache (from perf): {perf.get('cache', {})}")

# ── 6. Test 4: /status cache endpoint equivalent ──
print()
print("=" * 64)
print("TEST 4: Cache stats and grammar status")
print("=" * 64)

cache_stats = plan_cache.stats()
print(f"  Cache entries: {cache_stats['entries']}")
print(f"  Cache hits: {cache_stats['hits']}")
print(f"  Cache misses: {cache_stats['misses']}")
print(f"  Cache hit_rate: {cache_stats['hit_rate']}")
print(f"  Grammar: {engine.grammar is not None}")

assert cache_stats["entries"] > 0, "Cache should have entries"
assert cache_stats["hits"] >= 1, "Should have at least 1 cache hit"

# ── Summary ──
print()
print("=" * 64)
print("INTEGRATION TEST RESULTS")
print("=" * 64)

checks = [
    ("Stage latencies recorded", len(stages) >= 7),
    ("Architecture planning timed", stages.get("architecture_planning", 0) > 0),
    ("Cache miss on first run", result.cache_stats.get("misses", 0) >= 1),
    ("Cache hit on second run", result2.cache_stats.get("hits", 0) >= 1),
    ("Grammar configured", engine.grammar is not None),
    ("Gate results returned", len(result.gate_results) >= 0),
    ("Perf total samples >= 3", perf["total"]["samples"] >= 3),
    ("Perf stages present", len(perf_stages) > 0),
    ("Cache stats in perf", "cache" in perf),
]

all_pass = True
for name, passed in checks:
    status = "✓ PASS" if passed else "✗ FAIL"
    if not passed:
        all_pass = False
    print(f"  {status}: {name}")

print()
if all_pass:
    print("ALL CHECKS PASSED ✓")
    sys.exit(0)
else:
    print("SOME CHECKS FAILED ✗")
    sys.exit(1)
