# DevForge — generation engine for the Forge stack.

The ``devforge`` package name is a historical fossil (the project was
once called "DevForge").  The engine lives at ``engine/devforge/`` and
is served as an MCP server by ``devforge.platform.mcp_server``.

## Key packages

- ``devforge.compilation.pipeline`` — prompt → file + operation plan
- ``devforge.execution`` — sends operations to godot-ai MCP server
- ``devforge.platform`` — MCP server entry point
- ``devforge.spatial`` — room/building/scatter/WFC planners
- ``devforge.knowledge`` — scene graph, system graph, lore
- ``devforge.reasoning`` — LLM planning and repair

See ``docs/current/CODE-ARCHITECTURE.md`` for a file-by-file map.
