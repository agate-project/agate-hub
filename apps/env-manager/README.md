# env-manager

A small page to paste API keys into the project's `.env`. **Values never pass through the AI**: the page posts them
straight to `agate.py env set NAME --stdin`, and the agent only sees `saved: NAME (fp:xxxxxx) · verified ✓`.

Installed **on demand** (never by default): `python3 .agate/agate.py add app:env-manager`.

## Use
```
python3 .agate/apps/env-manager/run.py --for clickup        # every variable a package needs, one form
python3 .agate/apps/env-manager/run.py --var EXA_API_KEY    # just these variables
python3 .agate/apps/env-manager/run.py                      # manage all: replace, add, verify, remove, new
python3 .agate/apps/env-manager/run.py --plan               # where it would open; changes nothing
```

## How it opens (decided in code, not by the model)
1. **Inside Orca** → Orca's browser (`orca tab create`). The server listens on `127.0.0.1` of the machine; Orca's
   browser reaches it without exposing anything. If the person's desktop isn't connected, it tries the next one.
2. **Local machine with a display** → your browser.
3. **Remote machine** → only via **Tailscale** with the `remote-preview` skill and an allowlist
   (`preview_identity:` in `memory/local/preferences.yml`). Anyone else on the tailnet gets 403.
4. **Remote without a private channel** → it says so and offers an **SSH port-forward** (the server still listens
   only on `127.0.0.1`). Public tunnels, claude.ai artifacts and pasting in the chat are never offered.
5. **Terminal** is always an alternative: `python3 .agate/agate.py env set NAME` (hidden input).

## Security
- One-time link (32-byte token, valid 10 minutes); after the first open it becomes an HttpOnly, SameSite=Strict
  session cookie and the link returns **410** if used again.
- Write-only: saved values are never sent to the browser; it shows status and fingerprints only.
- CSRF token on every change, same-origin check, `Cache-Control: no-store`, strict CSP, `127.0.0.1` only.
- Shuts down after saving (or after 10 minutes without activity). Nothing stays listening.
- First run shows the risks once (a compromised computer or browser can read anything typed, with any method);
  the answer is saved in `memory/local/preferences.yml` (`consents.env_manager`).

## Agate Desktop
This is a mini standalone page on purpose. When Agate Desktop exists, the same UI (same files, same endpoints) will
be embedded in its window (Electron) instead of opening a browser tab; the security rules stay the same.
