"""Shared helpers for Agate hub apps (stdlib only).

The same file ships inside every app folder, so each app installs on its own (`.agate/apps/<name>/`).
It finds the project root, calls the base CLI, reads/writes the small YAML preference files, resolves the UI
language and decides PROGRAMMATICALLY how a local page can be opened for the person (never the model).
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import webbrowser
from datetime import date

AGATE = os.path.join(".agate", "agate.py")


# ---------------------------------------------------------------- project

def find_root(start=None):
    """Nearest folder with .agate/agate.py (an Agate project)."""
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, AGATE)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise SystemExit("Not inside an Agate project (no .agate/agate.py found).")
        d = parent


def run_agate(root, args, stdin=None, timeout=60):
    """Run `python3 .agate/agate.py <args>` in the project. Returns (returncode, stdout, stderr).

    Secrets only ever travel on stdin; they are never part of `args`.
    """
    cmd = [sys.executable, os.path.join(root, AGATE)] + list(args)
    try:
        p = subprocess.run(cmd, cwd=root, input=stdin, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


# ---------------------------------------------------------------- tiny YAML (flat + one nesting level)

def read_yaml(path):
    """Read `key: value` lines and one nested level (`parent:` + indented `child: value`)."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    parent = None
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#") or raw.strip() == "---":
            continue
        indented = raw[:1] in (" ", "\t")
        if ":" not in raw:
            continue
        key, val = raw.strip().split(":", 1)
        key, val = key.strip(), val.split(" #", 1)[0].strip().strip("\"'")
        if indented and parent is not None:
            out.setdefault(parent, {})
            if isinstance(out[parent], dict):
                out[parent][key] = val
            continue
        if val == "":
            parent = key
            out[key] = {}
        else:
            parent = None
            out[key] = val
    return out


def set_nested(path, parent, key, value):
    """Set `parent.key: value` in a small YAML file, keeping everything else as it is."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    out, i, done = [], 0, False
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if not done and re.match(r"^%s:\s*$" % re.escape(parent), line):
            j = i + 1
            block = []
            while j < len(lines) and lines[j][:1] in (" ", "\t"):
                block.append(lines[j])
                j += 1
            block = [b for b in block if not re.match(r"^\s+%s:" % re.escape(key), b)]
            block.append("  %s: %s" % (key, value))
            out.extend(block)
            i = j
            done = True
            continue
        i += 1
    if not done:
        out += ["%s:" % parent, "  %s: %s" % (key, value)]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out).strip("\n") + "\n")


def _frontmatter_value(path, key):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f.read().splitlines()[:30]:
                if line.lower().startswith(key + ":"):
                    return line.split(":", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def prefs_path(root):
    return os.path.join(root, "memory", "local", "preferences.yml")


def preferences(root):
    return read_yaml(prefs_path(root))


def language(root):
    """Reply language: local preference, then project default (YAML first, then the 0.4.0 Markdown files)."""
    local = os.path.join(root, "memory", "local")
    shared = os.path.join(root, "memory", "shared")
    for value in (read_yaml(os.path.join(local, "preferences.yml")).get("language"),
                  _frontmatter_value(os.path.join(local, "preferences.md"), "language"),
                  read_yaml(os.path.join(shared, "project.yml")).get("default_language"),
                  _frontmatter_value(os.path.join(shared, "project.md"), "default_language")):
        if isinstance(value, str) and value:
            return value.lower()[:2]
    return ""


def identities(root):
    """Allowlist for remote access (preview_identity), shared with the remote-preview skill."""
    local = os.path.join(root, "memory", "local")
    val = read_yaml(os.path.join(local, "preferences.yml")).get("preview_identity")
    if not isinstance(val, str) or not val:
        val = _frontmatter_value(os.path.join(local, "preferences.md"), "preview_identity") or ""
    return [v.strip().lower() for v in val.split(",") if v.strip()]


def today():
    return date.today().isoformat()


# ---------------------------------------------------------------- where are we?

def facts(env=None, which=shutil.which, system=None):
    """What the launcher knows about the place it runs in. Pure inputs → easy to test."""
    env = os.environ if env is None else env
    system = system or platform.system()
    in_orca = bool(env.get("ORCA_AGENT_SESSION_ID") or env.get("ORCA_CLI_COMMAND")) and bool(which("orca"))
    ssh = bool(env.get("SSH_CONNECTION") or env.get("SSH_TTY"))
    orca_remote = bool(env.get("ORCA_REMOTE_PAIRING"))
    if system in ("Darwin", "Windows"):
        display = not ssh
    else:
        display = bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")) and not ssh and not orca_remote
    return {"in_orca": in_orca, "remote": ssh or orca_remote or not display, "display": display,
            "ssh": ssh, "orca_remote": orca_remote, "tailscale": bool(which("tailscale"))}


def plan(f, preview_skill, allow):
    """Ordered UI channels to try, plus why some were skipped. Terminal is always offered separately.

    Excluded on purpose, in code: public tunnels, claude.ai artifacts, pasting values in the chat.
    """
    modes, skipped = [], []
    if f["in_orca"]:
        modes.append("orca")
    if f["display"] and not f["remote"]:
        modes.append("local")
    if f["remote"]:
        if not f["tailscale"]:
            skipped.append("tailscale: not installed")
        elif not preview_skill:
            skipped.append("tailscale: needs the remote-preview skill (`python3 .agate/agate.py add "
                           "agate/remote-preview`)")
        elif not allow:
            skipped.append("tailscale: no allowlist; save `preview_identity: <your tailscale login>` in "
                           "memory/local/preferences.yml")
        else:
            modes.append("tailscale")
    return modes, skipped


def where_line(f):
    """One line saying explicitly whether this looks local or remote, and why."""
    if not f["remote"]:
        return "machine: local (display available)"
    why = []
    if f.get("ssh"):
        why.append("SSH session")
    if f.get("orca_remote"):
        why.append("Orca remote host")
    if not f["display"]:
        why.append("no display")
    return "machine: REMOTE (" + ", ".join(why or ["no display"]) + ")"


def ssh_forward(port, env=None):
    """The SSH port-forward the person can run on their own computer (always private)."""
    env = os.environ if env is None else env
    user = env.get("USER") or env.get("LOGNAME") or "user"
    conn = (env.get("SSH_CONNECTION") or "").split()
    host = conn[2] if len(conn) >= 3 else (platform.node() or "this-server")
    return "ssh -N -L %d:127.0.0.1:%d %s@%s   (then open http://127.0.0.1:%d/ on your computer)" % (
        port, port, user, host, port)


NO_PRIVATE_CHANNEL = ("Remote machine without a private channel (Tailscale / Cloudflare Access / Orca). Options: "
                      "install Tailscale, open the project in Orca, or use an SSH port-forward (command: {ssh}). "
                      "Public tunnels are not offered.")


def preview_skill_dir(root):
    for rel in (os.path.join(".agents", "skills", "remote-preview"), os.path.join(".claude", "skills",
                                                                                   "remote-preview")):
        d = os.path.join(root, rel)
        if os.path.isfile(os.path.join(d, "preview.py")):
            return d
    return None


def open_orca(url):
    """Open the URL in Orca's browser. False if the person's desktop is not connected."""
    try:
        p = subprocess.run(["orca", "tab", "create", "--url", url], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False, "orca not answering"
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip()
        return False, "browser_host_unavailable" if "browser_host_unavailable" in msg else (msg[:120] or "failed")
    return True, ""


def open_local(url):
    try:
        return bool(webbrowser.open(url)), ""
    except webbrowser.Error as e:
        return False, str(e)


def expose_tailscale(root, port):
    """Publish 127.0.0.1:<port> on the tailnet with the remote-preview Tailscale provider (never Funnel)."""
    d = preview_skill_dir(root)
    if not d:
        return None, None, "remote-preview skill not installed"
    if d not in sys.path:
        sys.path.insert(0, d)
    try:
        from providers.tailscale import PROVIDER  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return None, None, "cannot load the Tailscale provider: %s" % e
    ok, why = PROVIDER.available()
    if not ok:
        return None, None, why
    try:
        res = PROVIDER.expose(port, {"root": root})
    except Exception as e:  # noqa: BLE001
        return None, None, str(e)
    if not res.get("url"):
        return None, res.get("handle"), res.get("note") or "manual step needed"
    return res["url"], (PROVIDER, res.get("handle")), ""


def unexpose(handle):
    if handle and isinstance(handle, tuple):
        prov, h = handle
        try:
            prov.stop(h)
        except Exception:  # noqa: BLE001
            pass


def jsonable(obj):
    return json.loads(json.dumps(obj, default=str))
