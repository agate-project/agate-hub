---
name: quick-start
description: "Guided start for a new Agate project and import of what the person already uses elsewhere. Use when the person asks for a quick start, to set up or onboard this project, or to bring in a Claude memory export, prompts, agents, skills, CLAUDE.md/AGENTS.md or files from other projects."
---

# Quick start

Only when the person asked for it. Keep it a conversation, not a form.

## 1. Ask (max 4 questions, skip what is already known)
Check first: the top of `AGENTS.md`, `memory/shared/project.yml`, `memory/local/preferences.yml` and what the person
already said in this chat. Then ask only what is missing, one or two at a time, in the person's language:
1. What is this project about and what do you want to achieve?
2. Who uses it (just you, a team, which roles)?
3. Which language should I reply in? (usually obvious from how they write: don't ask, just confirm)
4. How do you like to work with me (e.g. ask before assuming, or assume and let you review at the end)?

## 2. Save
- Top of `AGENTS.md`, **outside** the `agate` block: replace the `# Project name` title and the placeholder paragraph
  with the project name and 2–3 lines from answers 1–2.
- Language: `python3 .agate/agate.py lang set <code> --project` (writes `memory/local/preferences.yml` and the
  project default in `memory/shared/project.yml`).
- `memory/shared/project.yml`: add `description: <one line>` (keep `default_language`).
- The person's working style: `style: <one line>` in `memory/local/preferences.yml` (or
  `memory/local/people/<name>.yml` if several people share this checkout), plus `name:` if they told you.

## 3. Offer, only if it fits
If the answers point to a specific kind of work (e.g. product discovery, specs, metrics), offer the matching
extension in one line (`python3 .agate/agate.py add product`). Don't install anything without their ok.

## 4. Import what you already use (offer it once)
Ask whether they have things to bring: a Claude memory export (claude.ai → Settings → export their data or copy what
Claude remembers into a .md), prompts or notes, Claude Code agents (`.claude/agents/*.md`), skills folders,
`CLAUDE.md`/`AGENTS.md` or files from other projects (folders or a .zip). Then:
1. `python3 .agents/skills/quick-start/import.py scan <paths…>` → a short plan per item.
2. Explain the plan in plain words. Agents become skills (steps and criteria kept, persona trimmed); before keeping a
   converted agent, check `python3 .agate/agate.py search <topic>` for an existing skill that already does it.
3. With their ok: `import.py apply --yes`. It copies documents, creates skills, saves memory entries and the
   person's style, and appends project context to the "This project" section of `AGENTS.md`. It never copies secrets.
4. Do what it lists as left: offer the connectors it found (`.agate/core/guides/mcp-add.md`, official first) and
   register key names with `agate.py env add` (values via env-manager or the terminal, never the chat).
Details and examples: `references/import.md`. This skill includes a script, so installing it asks for consent.

## 5. Close
Two lines: what you saved and where. Then continue with whatever they wanted to do.
