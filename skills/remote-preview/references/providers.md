# Providers

| Provider | Privacy | Who can open it | Identity header | Needs |
|---|---|---|---|---|
| `tailscale` | private (with allowlist) | Only allowlisted Tailscale logins | `Tailscale-User-Login` | `tailscale` running; `serve` may need admin rights |
| `cloudflare-access` | private | Only emails allowed by the Access policy | `Cf-Access-Authenticated-User-Email` | `cloudflared`, a Cloudflare account and a named tunnel |
| `orca` | private | The person, in Orca's built-in browser | none | `orca` CLI; Orca's browser must reach this machine |
| `ssh` | private | The person, through their own SSH tunnel | none (SSH authenticates) | SSH access to this machine |
| `cloudflare-quick` | **public** | Anyone with the link | none | `cloudflared`; `--i-understand-public` + explicit ok |

Selection: most private available first; ties broken by the order above. `--via` forces one.

## tailscale
- Runs `tailscale serve --bg --https=<port> http://127.0.0.1:<local>` on a free port between 8444 and 8499,
  skipping ports already in `tailscale serve status --json` (never overwrites someone else's).
- **A tailnet is not just you.** Every device the tailnet's access rules allow can reach a `serve` URL. The
  preview server therefore checks `Tailscale-User-Login` and answers 403 to anyone not in the allowlist. Devices
  tagged as servers send no login, so they get 403 too.
- Assumes Tailscale sets the identity header itself on proxied requests (it does for `serve`); processes on this
  same machine can reach the local port directly, so on a shared machine the other users of it are trusted.
- Permission errors: retries once with `sudo -n` (no password prompt). If that fails, prints the exact command for
  the person to run.
- **Never Funnel** (`tailscale funnel`): it publishes to the internet. This skill doesn't call it.
- Stop: `tailscale serve --https=<port> off`.

## cloudflare-access
- Needs a one-time setup (domain on Cloudflare, `cloudflared tunnel login`, `tunnel create`, `tunnel route dns`,
  and an Access application allowing only the person's email). Then `AGATE_CF_TUNNEL` and `AGATE_CF_HOSTNAME` in
  `.env`.
- Runs `cloudflared tunnel run --url http://127.0.0.1:<local> <tunnel>`; the allowlist uses the Access email header.

## orca
- When the agent runs inside Orca, `orca ports --json` lists the ports Orca detected. Whether Orca's built-in
  browser reaches a remote host's localhost depends on how Orca is connected: test once and note the result in
  `memory/local/`.

## ssh
- Prints `ssh -N -L <port>:127.0.0.1:<port> <user>@<host>` for the person to run on their computer; then they open
  `http://127.0.0.1:<port>/` there.

## cloudflare-quick (public)
- `cloudflared tunnel --url http://127.0.0.1:<local>` → a random `*.trycloudflare.com` URL. Anyone with the link
  can open it; there is no identity to check. Only with the person's explicit ok, for short-lived sharing, and
  stop it right after.

## Troubleshooting
- `serve` says "no allowlist": ask the person for their Tailscale login (e.g. `name@example.com` as shown in the
  Tailscale admin) or Access email, save `preview_identity: <id>` in `memory/local/preferences.yml`.
- 403 for the person: their identity differs from the allowlist (check the login Tailscale shows for their device).
- 502: the dev server behind `--port` isn't answering.
- WebSockets and server-sent streaming through `--port` aren't proxied; expose the dev server directly with the
  provider if the page needs live reload.
- Leftovers: `preview.py list` and `preview.py stop all`.
