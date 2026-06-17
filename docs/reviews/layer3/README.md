# Layer 3 — Code-Health Review responses

Raw external input from CLI AIs answering the prompts in
`docs/current/LAYER3-CODE-SURVEY-PROMPTS.md`.

Each reviewer writes **one** file here:

```
RESPONSE-<name>.md      e.g. RESPONSE-codex.md, RESPONSE-gemini.md,
                             RESPONSE-claude.md, RESPONSE-cursor.md
```

Copy `_TEMPLATE.md` to that filename and fill in only the prompts you answered.
This is the **only** file a reviewer is allowed to write — everything else in the
repository is read-only for this exercise.

These are raw notes, not decisions. They get reconciled against the real codebase
and distilled into a conventions doc + an architecture ADR + a god-file split
plan, owner-approved before any code changes.
