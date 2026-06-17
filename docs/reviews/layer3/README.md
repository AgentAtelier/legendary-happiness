# Layer 3 — Code-Health Review responses

Raw external input from CLI AIs answering the prompt block in
`docs/current/LAYER3-CODE-SURVEY-PROMPTS.md`.

Each reviewer writes exactly **one** file here, named by **you** (not the AI)
before you paste the prompt:

```
response-codex.md   response-gemini.md   response-claude.md   response-cursor.md
```

The prompt is self-contained: the report structure is inlined, and the AI is told
to write only its one assigned file and never to open or modify anything else in
this folder. That keeps each AI from clobbering the previous one's report.

These are raw notes, not decisions. They get reconciled against the real codebase
and distilled into a conventions doc + an architecture ADR + a god-file split
plan, owner-approved before any code changes.
