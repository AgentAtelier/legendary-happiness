# DevForge

Autonomous Godot development pipeline with planning, patching, validation, and repair loops.

## Environment

- Python: `3.12.3`
- Virtualenv: `.venv`
- Neo4j: `5.x` (Docker)
- Godot: `4.x` (headless available in `PATH`)

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Neo4j (GraphRAG)

Start Neo4j locally:

```bash
docker run -d --name neo4j -p 7687:7687 -e NEO4J_AUTH=neo4j/testpassword neo4j:5
```

Connection defaults used by tests/code:

- URI: `bolt://localhost:7687`
- User: `neo4j`
- Password: `testpassword`
- Database: `neo4j`

Override with env vars:

- `DEVFORGE_NEO4J_URI`
- `DEVFORGE_NEO4J_USER`
- `DEVFORGE_NEO4J_PASSWORD`
- `DEVFORGE_NEO4J_DATABASE`

Run GraphRAG tests:

```bash
.venv/bin/pytest -q tests/knowledge
```

## AST Parser / Grammar Build

`devforge/patch/gdscript_ast.py` supports query operations with a regex fallback and optional tree-sitter backend.

Grammar source is vendored at:

- `devforge/patch/grammars/tree-sitter-gdscript/`

Build shared grammar library:

```bash
cd devforge/patch/grammars/tree-sitter-gdscript
npm ci
npm run build
# expected output: build/gdscript.so
```

AST tests:

```bash
.venv/bin/pytest -q tests/ast
```

## Test Commands

Non-LLM default suite:

```bash
.venv/bin/pytest tests/ -v --tb=short -k "not llm"
```

Focused suites:

```bash
.venv/bin/pytest -q tests/knowledge
.venv/bin/pytest -q tests/ast
```
