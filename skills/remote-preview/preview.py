#!/usr/bin/env python3
"""remote-preview: show a local folder or dev server to the person, privately, when the agent runs remotely.

Commands:
  detect                                   remote hints, providers (most private first), ports Orca sees
  serve <dir> | --port N [--via P] [--allow ID]... [--no-expose] [--i-understand-public]
  expose <id> --via P [--i-understand-public]
  list
  stop <id>|all
  extension status|approve                 project providers in .agate/project/preview.py

State lives in memory/local/ (previews.json, previews/<id>.log|.pid, approvals.json).
Output is short on purpose: whatever it prints goes into the agent's context.
"""
import argparse
import hashlib
import http.client
import http.server
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from functools import partial

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

import providers  # noqa: E402
from providers import proc  # noqa: E402
from providers.base import ProviderError, choose, order_key  # noqa: E402

HEALTH = "/__preview_health"
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "host"}
EXT_REL = os.path.join(".agate", "project", "preview.py")
APPROVAL_KEY = "remote-preview"


# ---------- project paths and state ----------

def find_root(start=None):
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.exists(os.path.join(d, ".git")) or os.path.exists(os.path.join(d, "AGENTS.md")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(start or os.getcwd())
        d = parent


def state_dir(root):
    d = os.environ.get("AGATE_PREVIEW_STATE") or os.path.join(root, "memory", "local")
    os.makedirs(os.path.join(d, "previews"), exist_ok=True)
    return d


def registry_path(root):
    return os.path.join(state_dir(root), "previews.json")


def load_registry(root):
    try:
        with open(registry_path(root)) as f:
            return json.load(f).get("previews", [])
    except (OSError, ValueError):
        return []


def save_registry(root, items):
    with open(registry_path(root), "w") as f:
        json.dump({"previews": items}, f, indent=2)
        f.write("\n")


def read_identity(root):
    """preview_identity from memory/local/preferences.yml (0.4.1+), falling back to the 0.4.0 preferences.md."""
    for name in ("preferences.yml", "preferences.md"):
        try:
            with open(os.path.join(state_dir(root), name), encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in lines:
            if line.strip().lower().startswith("preview_identity:"):
                val = line.split(":", 1)[1].split(" #", 1)[0].strip().strip("\"'")
                return [v.strip().lower() for v in val.split(",") if v.strip()]
    return []


# ---------- local or remote, and is there a private channel? ----------

NO_PRIVATE_CHANNEL = ("Remote machine without a private channel (Tailscale / Cloudflare Access / Orca). Options: "
                      "install Tailscale, open the project in Orca, or use an SSH port-forward (command: {ssh}). "
                      "Public tunnels are not offered.")


def machine(env=None):
    """(is_remote, reasons). Explicit about why this does not look like the person's own computer."""
    env = os.environ if env is None else env
    why = []
    if env.get("SSH_CONNECTION") or env.get("SSH_CLIENT") or env.get("SSH_TTY"):
        why.append("SSH session")
    if env.get("ORCA_REMOTE_PAIRING"):
        why.append("Orca remote host")
    if sys.platform.startswith("linux") and not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        why.append("no display")
    return bool(why), why


def private_channel(provs, env=None):
    """Name of an available private channel, or None. Orca counts only inside an Orca session."""
    env = os.environ if env is None else env
    for p in provs:
        if p.name in ("tailscale", "cloudflare-access") and p.available()[0]:
            return p.name
    if (env.get("ORCA_AGENT_SESSION_ID") or env.get("ORCA_CLI_COMMAND")) and any(
            p.name == "orca" and p.available()[0] for p in provs):
        return "orca"
    return None


def ssh_hint(port):
    try:
        from providers.ssh import ssh_target
        user, host = ssh_target()
    except Exception:
        user, host = os.environ.get("USER", "user"), "this-server"
    return "ssh -N -L {p}:127.0.0.1:{p} {u}@{h}".format(p=port, u=user, h=host)


# ---------- project providers (approved only) ----------

def _git(root, *args):
    try:
        p = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _approvals_path(root):
    return os.path.join(state_dir(root), "approvals.json")


def _load_approvals(root):
    try:
        with open(_approvals_path(root)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def approve_extension(root):
    path = os.path.join(root, EXT_REL)
    data = _load_approvals(root)
    data[APPROVAL_KEY] = {"sha256": _sha(path), "approved": time.strftime("%Y-%m-%d")}
    with open(_approvals_path(root), "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def extension_state(root):
    """Returns (exists, approved, reason)."""
    path = os.path.join(root, EXT_REL)
    if not os.path.isfile(path):
        return False, False, "no project providers"
    digest = _sha(path)
    if _load_approvals(root).get(APPROVAL_KEY, {}).get("sha256") == digest:
        return True, True, "approved"
    code, _ = _git(root, "rev-parse", "--git-dir")
    if code != 0:
        approve_extension(root)
        return True, True, "auto-approved (not a git repo)"
    code, status = _git(root, "status", "--porcelain", "--", EXT_REL)
    if code == 0 and status:
        approve_extension(root)
        return True, True, "auto-approved (your uncommitted change)"
    _, me = _git(root, "config", "user.email")
    _, author = _git(root, "log", "-1", "--format=%ae", "--", EXT_REL)
    if me and author and me.lower() == author.lower():
        approve_extension(root)
        return True, True, "auto-approved (last change is yours)"
    return True, False, "changed by someone else: review it, then `preview.py extension approve`"


def project_providers(root):
    exists, approved, reason = extension_state(root)
    if not exists:
        return [], None
    if not approved:
        return [], "project providers skipped: " + reason
    spec = importlib.util.spec_from_file_location("agate_project_preview", os.path.join(root, EXT_REL))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # a broken extension must not break the built-in providers
        return [], "project providers failed to load: %s" % e
    return list(getattr(mod, "PROVIDERS", [])), None


def all_providers(root):
    extra, warning = project_providers(root)
    return providers.builtin() + extra, warning


def by_name(provs, name):
    for p in provs:
        if p.name == name:
            return p
    return None


# ---------- the preview server (allowlist + static dir or reverse proxy) ----------

class _Handler(http.server.SimpleHTTPRequestHandler):
    identity_header = None
    allow = ()
    upstream = None

    def log_message(self, fmt, *args):  # keep the log short
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _authorized(self):
        if self.path.split("?", 1)[0] == HEALTH:
            return True
        if not self.identity_header:
            return True
        who = (self.headers.get(self.identity_header) or "").strip().lower()
        return bool(who) and who in self.allow

    def _deny(self):
        body = b"403: not allowed for this preview\n"
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _health(self):
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        conn = http.client.HTTPConnection("127.0.0.1", self.upstream, timeout=60)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except OSError as e:
            msg = ("502: upstream 127.0.0.1:%d not answering (%s)\n" % (self.upstream, e)).encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        finally:
            conn.close()
        self.send_response(resp.status, resp.reason)
        for k, v in resp.getheaders():
            if k.lower() not in HOP and k.lower() != "content-length":
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _dispatch(self, static):
        if not self._authorized():
            return self._deny()
        if self.path.split("?", 1)[0] == HEALTH:
            return self._health()
        if self.upstream:
            return self._proxy()
        if static is None:
            self.send_error(405)
            return
        return static()

    def do_GET(self):
        self._dispatch(super().do_GET)

    def do_HEAD(self):
        self._dispatch(super().do_HEAD)

    def do_POST(self):
        self._dispatch(None)

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST


def make_server(port, directory=None, upstream=None, identity_header=None, allow=()):
    attrs = {"identity_header": identity_header or None,
             "allow": tuple(a.strip().lower() for a in allow if a.strip()),
             "upstream": upstream}
    handler_cls = type("PreviewHandler", (_Handler,), attrs)
    handler = partial(handler_cls, directory=directory or os.getcwd())
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    srv.daemon_threads = True
    return srv


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_health(port, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, HEALTH), timeout=1) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.1)
    return False


# ---------- commands ----------

def cmd_detect(root, args):
    remote_now, why = machine()
    print("machine: %s" % (("REMOTE (" + ", ".join(why) + ")") if remote_now else "local"))
    hints = []
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        hints.append("ssh session")
    if any(k.startswith("ORCA") for k in os.environ):
        hints.append("running under Orca")
    if os.path.exists("/.dockerenv"):
        hints.append("container")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        hints.append("no local display")
    remote = "yes" if "ssh session" in hints else ("likely" if hints else "unknown")
    print("remote: %s%s" % (remote, (" (" + ", ".join(hints) + ")") if hints else ""))
    provs, warning = all_providers(root)
    print("providers (most private first):")
    for p in sorted(provs, key=order_key):
        ok, why = p.available()
        tag = "%s, %s%s" % (p.privacy, "identity: " + p.identity_header if p.identity_header else "no identity header",
                            ", manual" if p.manual else "")
        print("  %-18s %-3s %s%s" % (p.name, "ok" if ok else "no", tag, "" if ok else " — " + why.split(". ")[0]))
    if warning:
        print(warning)
    best = choose(provs)
    print("default: %s" % (best.name if best else "none"))
    if remote_now and not private_channel(provs):
        print("WARNING: " + NO_PRIVATE_CHANNEL.format(ssh=ssh_hint("<port>")))
    try:
        from providers.orca import orca_ports
        ports = orca_ports()
    except Exception:
        ports = None
    if ports is not None:
        items = ports
        if isinstance(items, dict):
            items = (items.get("result") or {}).get("ports", items.get("ports"))
        if isinstance(items, list):
            listed = ", ".join(str(i.get("port", i)) if isinstance(i, dict) else str(i) for i in items[:12])
            print("orca ports: %s" % (listed or "none"))
    who = read_identity(root)
    print("allowlist: %s" % (", ".join(who) if who else "not set (ask the person; save preview_identity: in "
                                                          "memory/local/preferences.yml)"))
    return 0


def _spawn(root, entry_id, port, directory, upstream, header, allow):
    sd = state_dir(root)
    log_path = os.path.join(sd, "previews", entry_id + ".log")
    cmd = [sys.executable, os.path.abspath(__file__), "_serve", "--port", str(port),
           "--header", header or "", "--allow", ",".join(allow), "--pidfile",
           os.path.join(sd, "previews", entry_id + ".pid")]
    cmd += ["--dir", os.path.abspath(directory)] if directory else ["--upstream", str(upstream)]
    log = open(log_path, "ab")
    p = subprocess.Popen(cmd, cwd=root, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    return p.pid, log_path


def _expose(root, entry, prov, allow_public):
    ctx = {"allow_public": allow_public,
           "log_path": os.path.join(state_dir(root), "previews", entry["id"] + "." + prov.name + ".log")}
    res = prov.expose(entry["port"], ctx)
    entry.update({"provider": prov.name, "url": res.get("url"), "handle": res.get("handle") or {},
                  "manual": res.get("manual")})
    return res


def _print_entry_result(entry, res):
    print("id: %s · local: http://127.0.0.1:%d/ · provider: %s" % (entry["id"], entry["port"], entry.get("provider")))
    if res.get("url") and not res.get("manual"):
        print("url: " + res["url"])
    if res.get("note"):
        print(res["note"])


def cmd_serve(root, args):
    if not args.dir and not args.port:
        print("give a folder or --port N", file=sys.stderr)
        return 2
    if args.dir and not os.path.isdir(args.dir):
        print("not a folder: %s" % args.dir, file=sys.stderr)
        return 2
    provs, warning = all_providers(root)
    if warning:
        print(warning)
    prov = None
    if not args.no_expose:
        prov = by_name(provs, args.via) if args.via else choose(provs, allow_public=args.i_understand_public)
        if prov is None:
            print("no usable provider%s; run `preview.py detect`" % (" named " + args.via if args.via else ""),
                  file=sys.stderr)
            return 2
        ok, why = prov.available()
        if not ok:
            print("%s not available: %s" % (prov.name, why), file=sys.stderr)
            return 2
        remote_now, _ = machine()
        if remote_now and not private_channel(provs) and prov.privacy == "public":
            print("WARNING: " + NO_PRIVATE_CHANNEL.format(ssh=ssh_hint("<port>")), file=sys.stderr)
            return 2
        if prov.privacy == "public" and not args.i_understand_public:
            print("%s is PUBLIC: needs --i-understand-public and the person's explicit ok" % prov.name,
                  file=sys.stderr)
            return 2
    header = prov.identity_header if prov else None
    allow = [a.lower() for a in (args.allow or [])] or read_identity(root)
    if header and not allow:
        print("no allowlist: ask the person for their %s identity and save it as `preview_identity:` in "
              "memory/local/preferences.yml (or pass --allow)" % prov.name, file=sys.stderr)
        return 2
    entry_id = time.strftime("p%m%d%H%M%S")
    port = free_port()
    if prov is not None and machine()[0] and not private_channel(provs):
        print("WARNING: " + NO_PRIVATE_CHANNEL.format(ssh=ssh_hint(port)))
    pid, log_path = _spawn(root, entry_id, port, args.dir, args.port, header, allow)
    if not wait_health(port):
        proc.kill(pid)
        print("preview server didn't start; see %s" % log_path, file=sys.stderr)
        return 1
    entry = {"id": entry_id, "pid": pid, "port": port, "target": args.dir or "port %d" % args.port,
             "identity_header": header, "allow": allow, "created": time.strftime("%Y-%m-%d %H:%M"),
             "provider": None, "url": None, "handle": {}}
    res = {}
    if prov:
        try:
            res = _expose(root, entry, prov, args.i_understand_public)
        except ProviderError as e:
            proc.kill(pid)
            print("%s failed: %s" % (prov.name, e), file=sys.stderr)
            return 1
    items = load_registry(root)
    items.append(entry)
    save_registry(root, items)
    _print_entry_result(entry, res)
    return 0


def cmd_expose(root, args):
    items = load_registry(root)
    entry = next((e for e in items if e["id"] == args.id), None)
    if not entry:
        print("no preview %s" % args.id, file=sys.stderr)
        return 2
    provs, _ = all_providers(root)
    prov = by_name(provs, args.via)
    if not prov:
        print("unknown provider %s" % args.via, file=sys.stderr)
        return 2
    if (prov.identity_header or None) != (entry.get("identity_header") or None):
        print("this preview was started for a different identity check; stop it and `serve --via %s`" % prov.name,
              file=sys.stderr)
        return 2
    try:
        res = _expose(root, entry, prov, args.i_understand_public)
    except ProviderError as e:
        print("%s failed: %s" % (prov.name, e), file=sys.stderr)
        return 1
    save_registry(root, items)
    _print_entry_result(entry, res)
    return 0


def cmd_list(root, args):
    items = load_registry(root)
    if not items:
        print("no previews")
        return 0
    for e in items:
        state = "running" if proc.alive(e.get("pid")) else "stopped"
        print("%s  %-8s %-17s %s  %s" % (e["id"], state, e.get("provider") or "local-only", e.get("url") or
                                         "http://127.0.0.1:%d/" % e["port"], e.get("target", "")))
    return 0


def stop_entry(root, entry, provs):
    msg = None
    prov = by_name(provs, entry.get("provider") or "")
    if prov:
        try:
            prov.stop(entry.get("handle") or {})
        except ProviderError as e:
            msg = "%s: %s" % (prov.name, e)
    proc.kill(entry.get("pid"))
    return msg


def cmd_stop(root, args):
    items = load_registry(root)
    targets = items if args.id == "all" else [e for e in items if e["id"] == args.id]
    if not targets:
        print("no preview %s" % args.id, file=sys.stderr)
        return 2
    provs, _ = all_providers(root)
    rc = 0
    for e in targets:
        msg = stop_entry(root, e, provs)
        if msg:
            print("stopped the server, but the provider needs a manual step: " + msg)
            rc = 1
        else:
            print("stopped %s" % e["id"])
    save_registry(root, [e for e in items if e not in targets])
    return rc


def cmd_extension(root, args):
    exists, approved, reason = extension_state(root)
    if args.action == "status":
        print("%s: %s" % (EXT_REL, reason if exists else "not present"))
        return 0
    if not exists:
        print("%s not present" % EXT_REL, file=sys.stderr)
        return 2
    approve_extension(root)
    print("approved %s" % EXT_REL)
    return 0


def cmd_internal_serve(args):
    if args.pidfile:
        with open(args.pidfile, "w") as f:
            f.write(str(os.getpid()))
    allow = [a for a in (args.allow or "").split(",") if a]
    srv = make_server(args.port, directory=args.dir, upstream=args.upstream, identity_header=args.header or None,
                      allow=allow)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="preview.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect")
    s = sub.add_parser("serve")
    s.add_argument("dir", nargs="?")
    s.add_argument("--port", type=int, help="proxy an existing local server on this port")
    s.add_argument("--via")
    s.add_argument("--allow", action="append", help="identity allowed to open it (repeatable)")
    s.add_argument("--no-expose", action="store_true")
    s.add_argument("--i-understand-public", action="store_true")
    e = sub.add_parser("expose")
    e.add_argument("id")
    e.add_argument("--via", required=True)
    e.add_argument("--i-understand-public", action="store_true")
    sub.add_parser("list")
    st = sub.add_parser("stop")
    st.add_argument("id")
    x = sub.add_parser("extension")
    x.add_argument("action", choices=["status", "approve"])
    i = sub.add_parser("_serve")
    i.add_argument("--port", type=int, required=True)
    i.add_argument("--dir")
    i.add_argument("--upstream", type=int)
    i.add_argument("--header", default="")
    i.add_argument("--allow", default="")
    i.add_argument("--pidfile")
    args = ap.parse_args(argv)
    if args.cmd == "_serve":
        return cmd_internal_serve(args)
    root = find_root()
    return {"detect": cmd_detect, "serve": cmd_serve, "expose": cmd_expose, "list": cmd_list,
            "stop": cmd_stop, "extension": cmd_extension}[args.cmd](root, args)


if __name__ == "__main__":
    sys.exit(main())
