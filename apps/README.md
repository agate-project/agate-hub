# Apps

Small standalone tools with their own page, for things a chat does badly (typing secrets, seeing numbers at a
glance). Installed **only on demand**, never by default, and they add **no** always-loaded context: no skill, no
`AGENTS.md` lines. `agate.py start` mentions an app only when it's relevant (for example, missing keys).

```
python3 .agate/agate.py add app:<name>        # installs to .agate/apps/<name>/
python3 .agate/apps/<name>/run.py --help
```

| App | What it does |
|---|---|
| `env-manager` | Paste API keys into `.env` without them passing through the AI (one-time, write-only page through a private channel). |
| `context-meter` | How much context the project takes, per model family, with a trend and what to do. |

## Format
```
apps/<name>/
├── app.json      ← name, version, description, run, requires, installed_by_default: false
├── run.py        ← entry point; `--help` is short and enough; prints at most 3 lines to the agent
├── launch.py     ← shared helpers (same file in every app, so each one installs alone)
├── ui/           ← the page, if any
└── README.md     ← for people
```

## Rules
- The channel to open a page is decided **in code**: Orca's browser → local browser → Tailscale with an allowlist →
  SSH port-forward. Public tunnels, claude.ai artifacts and pasting secrets in the chat are never offered.
- Pages are **mini and standalone** (no desktop chrome) and reuse Agate's visual tokens, so Agate Desktop can embed
  them later.
- Everything in English; the UI follows the project's reply language (`memory/local/preferences.yml`).
