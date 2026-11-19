# Importing into an Agate project

`import.py scan` classifies; `import.py apply --yes` does the safe parts. Everything else is listed for the agent to
do with the person.

| Found | Recognized by | Goes to | How |
|---|---|---|---|
| Claude memory export | `.md`/`.json` mentioning "memory", bullet facts or a `memories` list | team facts → `memory/shared/`; personal preferences → `style` in `memory/local/preferences.yml` (+ notes) | `agate.py memory add` per fact (max 50; the rest to `documents/imported/`) |
| Agent prompt | `.md` with `name` + `description` frontmatter (e.g. `.claude/agents/*.md`) | `.agents/skills/<name>/SKILL.md` | converted: persona sections trimmed, flows kept |
| Skill | folder with `SKILL.md` | `.agents/skills/<name>/` | copied (secret lines dropped); check the library first |
| Instructions | `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, system prompt files | `AGENTS.md` › This project | appended under "Imported from …" to condense with the person; never inside the `agate` block |
| Notes, docs, data | other text, `.csv`, `.xlsx`, `.pdf`, `.docx`… | `documents/imported/` | copied + a line in `documents/INDEX.md` |
| Connectors | names like Figma, ClickUp, Notion, Linear, Amplitude; MCP URLs | — | offered: `.agate/core/guides/mcp-add.md` (official first, ask) |
| API key names | `*_API_KEY`, `*_TOKEN`, `*_SECRET` | `.env.example` | `agate.py env add NAME --where … --for …` (names only) |
| `.env`, credentials | file name | — | skipped; key-looking lines are dropped everywhere |

## From an agent prompt to an Agate skill (flows > roles)
Keep what the model can't know: when to use it, inputs, steps with gates, criteria with numbers, output format,
stop conditions, lessons learned. Trim biography and tone (decisions/0017: a perspective of 1–3 lines is enough).

Before (agent):
```
---
name: sam-pm
description: Senior PM. Use ONLY when called by name…
---
## IDENTITY
You are Sam, a senior PM with 15 years in LATAM entertainment products…
## PHASE 0 — BRIEFING
Ask up to 4 questions when context is missing…
## PHASE 6 — 3 PROPOSALS
At least 3 options, each with flow, risks and mitigations…
```
After (skill):
```
---
name: sam-pm
description: "Product discovery: briefing, benchmarks, ≥3 proposals with risks; stops for the person's choice."
---
## Perspective
A senior PM who challenges assumptions with data.
## PHASE 0 — BRIEFING
…
## PHASE 6 — 3 PROPOSALS
…
```
Then rewrite the description so it says **when** to use it (intent), not who it is, and drop "only when called by name"
if the person wants it to trigger by intent.
