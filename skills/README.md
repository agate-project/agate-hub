# Hub skills

Extra skills from Agate, installed one by one with `python3 .agate/agate.py add agate/<name>`.
None yet: the base ships `canvas` and `web-research`, and Anthropic's skills come from the library.

## Format
Each skill is an [Agent Skills](https://agentskills.io) folder:
```
skills/<name>/
├── SKILL.md       ← required: frontmatter `name` + `description`, then the instructions
├── agate.json     ← optional: {"version": "0.1.0", "requires": {...}} (same `requires` format as library.json)
└── …              ← scripts, references, assets
```
- `version` lets `agate.py update` tell what changed; installs pin the exact commit anyway.
- `requires` is checked by `agate.py doctor`.
