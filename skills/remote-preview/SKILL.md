---
name: remote-preview
description: Show a local HTML page, folder or dev server to the person when the agent runs on a remote machine (SSH session, cloud VPS, Orca remote runtime) and the person can't open localhost. Shares it privately (only the person's identity), via Tailscale, Cloudflare Access, an SSH tunnel or Orca. Use when you need to "show", "preview" or "share" something you built or are serving, or the person mentions tailscale or a private link.
---

# Remote preview

Run everything with `python3 .agents/skills/remote-preview/preview.py …` from the project root.

## Steps
1. `preview.py detect` — tells whether this is a remote machine, which providers are available (ordered from
   most to least private) and which local ports Orca sees.
2. Identity: the allowlist is the person's identity on the provider (their Tailscale login or their Cloudflare
   Access email). Read `preview_identity:` in `memory/local/preferences.md`; if it's missing, ask once and save it
   there. Never expose without an allowlist on a provider that sends an identity header.
3. Start and expose:
   - a folder: `preview.py serve <dir>`
   - a running dev server: `preview.py serve --port <N>`

   It picks the most private available provider; force one with `--via tailscale|cloudflare-access|ssh|orca`.
   Give the person the URL it prints (or, for `ssh`/`orca`, the instructions it prints).
4. When the person is done, or at the end of the work: `preview.py list` and `preview.py stop <id>` (or
   `stop all`). Don't leave previews running.

## Rules
- **Never public without explicit ok.** Public means anyone with the link: `cloudflare-quick` (trycloudflare)
  and Tailscale Funnel. Funnel is never used by this skill. `cloudflare-quick` needs `--i-understand-public` and
  you must tell the person, before running it, that the link is public and short-lived.
- A tailnet is not "only you": every device the tailnet's rules allow can reach a `tailscale serve` URL. That's
  why the preview server checks the identity header and answers 403 to anyone not in the allowlist.
- If a command needs admin rights and can't get them, `preview.py` prints the exact command: pass it to the
  person instead of looking for another way around.
- Reply in the person's language (project language rule).
- Provider details and troubleshooting: `references/providers.md`.

## Project providers
A project can add providers (a company VPN, ngrok…) in `.agate/project/preview.py` with a `PROVIDERS` list
(same interface as `providers/base.py`). It only runs once approved on this machine: own uncommitted changes are
approved automatically; for changes that came from someone else, `preview.py extension status` shows it and
`preview.py extension approve` approves it after the person reviewed the diff.
