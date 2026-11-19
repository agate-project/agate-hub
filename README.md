# Agate hub

Everything an Agate project can add **on demand**: extra skills and extensions. The base (`agate`) stays small;
each project downloads only what it uses from here.

```
agate-hub/
├── skills/<name>/        ← Agate's own extra skills (Agent Skills folders)
├── extensions/<name>/    ← extensions: skills + tools + an AGENTS.md block, with their own manifest
├── apps/<name>/          ← small standalone tools with their own page (env-manager, context-meter)
└── packs.json            ← named bundles (extensions and/or skills from any library source) and the apps list
```

## Install from a project
From the root of an Agate project:
```
python3 .agate/agate.py add <extension>                 # e.g. product (hub URL from .agate/library.json)
python3 .agate/agate.py add agate/<skill>        # one skill from this hub
python3 .agate/agate.py add pack:<name>          # a pack from .agate/library.json
```
Only the requested folder is downloaded (partial clone + sparse checkout), not the whole hub.

## Apps
Small tools with their own page, installed only on demand (`python3 .agate/agate.py add app:<name>` →
`.agate/apps/<name>/`). They add no always-loaded context (no skill, no `AGENTS.md` lines). See
[`apps/README.md`](apps/README.md).

## Versions and updates
- Each skill and each extension has **its own version** in its manifest (`agate.json` for skills,
  `.agate/expansions/<name>.json` for extensions).
- Every install records where it came from: repo, sub-path, exact commit and version (the extension manifest in the
  project, or `.agate/skills.lock.json` for skills).
- `python3 .agate/agate.py check` lists available updates for the base, each installed extension and each skill, without
  applying them. Skills are included in the same list (one lock for every package).

## Rules
- Everything here is in **English**: the agent reads it. People get replies in their own language.
- Nothing from a specific company or person: each business's context lives in its own project.
