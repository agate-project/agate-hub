<p align="center">
  <img src=".github/agate.svg" width="96" alt="Agate">
</p>

<h1 align="center">Agate hub</h1>

<p align="center">
  Everything an <a href="https://github.com/agate-project/agate">Agate</a> project can add <b>on demand</b>.<br>
  The base stays small; each project downloads only what it uses.
</p>

<p align="center">
  <img alt="release" src="https://img.shields.io/badge/release-v0.4.2-2c5d88">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-a8492a">
  <img alt="installs" src="https://img.shields.io/badge/installs-only%20from%20tags-2f6f4e">
</p>

---

## What's here
| | Name | What it does | Install |
|---|---|---|---|
| 🧩 skill | `remote-preview` | Show a local page or dev server from a remote machine, privately (Orca, Tailscale allowlist, SSH). | `add remote-preview` |
| 🧩 skill | `quick-start` | Optional guided start for a new project (max 4 questions). | `add quick-start` |
| 📦 extension | `product` | Product work: visible research, several options with risks, stop and wait for a choice. *(draft)* | `add product` |
| 🖥️ app | `env-manager` | A small private page to set API keys: values go straight to `.env`, never through the AI. | `add app:env-manager` |
| 🖥️ app | `context-meter` | A one-page report of how much context the project takes, with trends and recommendations. | `add app:context-meter` |

Run them from an Agate project: `python3 .agate/agate.py <command>`.

```
agate-hub/
├── skills/<name>/       Agent Skills folders (SKILL.md + optional agate.json)
├── extensions/<name>/   skills + tools + an AGENTS.md block, with their own manifest
├── apps/<name>/         small standalone tools with their own page
└── packs.json           named bundles
```

## How installs work
- **Only what you ask for.** Just that folder is downloaded (partial clone + sparse checkout).
- **Only from release tags** (`vX.Y.Z`), never from the branch tip; the project's lock records tag and commit.
- **Scripts ask first.** A package with scripts needs the person's ok, even from this hub; text-only skills install silently.
- **Zero context until used.** Apps add nothing to every message; `start` mentions them only when they're relevant.
- `python3 .agate/agate.py check` lists updates; `update` shows which scripts change before applying.

## Rules
- Everything is in **English** (the agent reads it); people get replies in their own language.
- Nothing from a specific company or person: each business's context lives in its own project.

## License
[Apache 2.0](LICENSE).
