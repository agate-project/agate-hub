---
name: remote-preview
description: "Share a local HTML page, artifact, canvas, folder or dev server with the person through a Tailscale link, when the agent runs on a remote machine (VPS, SSH, Orca remote) and the person can't open localhost. Use when you need to show, preview or share something, or the person mentions tailscale or a link."
---

# Remote preview

From the project root: `python3 .agents/skills/remote-preview/preview.py …`

1. Share it:
   - a page (artifact, canvas `index.html`): `preview.py serve artifacts/2026-11/x.html` — serves its folder and the
     link opens that page;
   - a folder: `preview.py serve <dir>`;
   - a server already running here (e.g. `agate.py serve` for live view and comments, a dev server):
     `preview.py serve --port <N> [--path artifacts/x.html]`.
2. Give the person the `link` it prints. It only opens from devices on the tailnet; nothing to ask or configure.
3. When they're done: `preview.py list`, `preview.py stop <id>` (or `stop all`).

Rules:
- It listens on this machine's Tailscale address only. Never `0.0.0.0`, never a public tunnel (Funnel,
  trycloudflare, ngrok).
- Don't ask for accounts, logins, emails or admin rights: none are needed. If it prints that Tailscale isn't active,
  pass on the options it lists (Orca's browser, SSH port-forward).
