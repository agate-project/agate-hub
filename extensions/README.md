# Agate expansions

An expansion adds to the base what a specific use needs (for example, product): skills, tools and instructions. It is
developed in the workspace and published inside the **hub** (`agate-hub/extensions/<name>/`); projects download only
the extensions they install.

The first one is `product` (in design: see `specs/product-expansion.md`, `tasks/TASKS.md` and `decisions/0011`).

## Format
Each expansion is a folder `extensions/<name>/` with **the same paths it will have inside a project**:

```
extensions/<name>/
├── .agate/expansions/<name>.json   ← manifest (required)
├── AGENTS.md                       ← only the expansion's block (see below)
├── README.md                       ← what it adds and how to install it (not copied into the project)
├── CHANGELOG.md
├── .agents/skills/<skill>/SKILL.md ← its skills
└── tools/<name>/                   ← its tools, if any
```

Manifest:
```json
{
  "name": "<name>",
  "version": "0.1.0",
  "requires": { "agate": ">=0.3.0" },
  "owned": [".agents/skills/<skill>/", "tools/<name>/"],
  "blocks": { "AGENTS.md": "agate-<name>" }
}
```

**Adjust a base line instead of adding one (`slots`).** The base's `agate` block has slots where an expansion can add
emphasis, e.g. `research_scope` in «When facts matter{…}, check sources…». The expansion gives only values; the base
owns the wording («(e.g. …)», so it focuses without limiting). Values from several expansions are merged, deduplicated
and capped at 8 per slot. Prefer a slot over a new line in the expansion's block.
```json
"slots": { "research_scope": ["market", "users", "competitors", "trends"] }
```
Result in `AGENTS.md`: `- When facts matter (e.g. market, users, competitors, trends), check sources…` (same line).
Slots today: `research_scope`.

The expansion's `AGENTS.md` contains only its block:
```
<!-- agate-<name>:begin -->
## <Name> (Agate expansion)
…instructions for this use…
<!-- agate-<name>:end -->
```

## Rules
- `owned` may only declare the expansion's own paths. `agate.py` refuses to overwrite what belongs to the base and
  never touches `memory/`, `documents/`, `artifacts/` or `archive/`.
- Everything compiled is in **English** (names and content): the agent reads it. People get replies, artifacts and
  documents in their own language (the base's Language rule).
- Nothing from a specific company goes into an expansion.

## Install
From the root of a project:
```
python3 .agate/agate.py add <name>                              # from the hub in .agate/library.json
python3 .agate/agate.py update --yes --from <hub-url-or-path>#extensions/<name>
```
`agate.py` copies what `owned` declares, adds or updates the `agate-<name>` block at the end of `AGENTS.md` and saves
the manifest in the project's `.agate/expansions/<name>.json`, and records where it came from (repo, sub-path, commit) in
`.agate/lock.json` so `agate.py check` can report updates. It warns if the project's base is older than what
`requires` asks for.
