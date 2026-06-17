---
reviewer: <YOUR NAME — e.g. codex / gemini-cli / claude-code / cursor>
date: <YYYY-MM-DD>
prompts_answered: [1, 2, 3]   # list only the ones you actually did
---

# Layer-3 Code-Health Review — <YOUR NAME>

> Reference real code as `path/to/file.py:line`. Be concrete and specific to THIS
> repository, not generic best-practice. Put the substance here, not in chat.

## Prompt 1 — One architecture + god-file splits
*(delete this whole section if you didn't answer Prompt 1)*

### Recommended architecture
*(one paragraph a non-coder can hold in their head)*

### Where the code follows it vs. muddies it
*(cite files)*

### God-file split plan
*(for each of `mcp_server.py`, `hub.py`, `engine.py`, `godot_ai_mcp.py`: the
target modules, each module's single responsibility, and a safe order — lowest
risk first)*

### What you're not asking that you should be

---

## Prompt 2 — Short conventions guide
*(delete if not answered)*

### File & function length
*(your recommended max + real offenders, with line counts)*

### Duplication to collapse into functions
*(real examples: `path:line`)*

### Naming convention
*(files / functions / modules — and any fossil/misleading names to fix)*

### The minimal "loose rules" worth standardizing
*(each rule + a one-line rationale; keep it few)*

### What you're not asking that you should be

---

## Prompt 3 — Review & navigation environment
*(delete if not answered)*

### Structural signals that make a file's purpose obvious

### What makes a diff reviewable by a non-coder

### Automated guardrails (most relief per unit of setup)

### What you're not asking that you should be

---

## Cross-cutting / anything else
