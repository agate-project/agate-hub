---
name: quick-start
description: Guided start for a new Agate project. Use when the person asks for a quick start, to set up this project, or for onboarding of a new Agate project. A short conversational intake (at most 4 questions) that saves what the project is about, who uses it, the reply language and how the person likes to work.
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

## 4. Close
Two lines: what you saved and where. Then continue with whatever they wanted to do.
