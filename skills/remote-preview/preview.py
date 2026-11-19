#!/usr/bin/env python3
"""remote-preview: share a local page, folder or dev server over the Tailscale network (tailnet).

Commands:
  detect                     is Tailscale up here, and the address links will use
  serve <file|dir>           serve it and print the link (a file: its folder is served, the link opens the file)
  serve --port N             share a local server (e.g. `agate.py serve`, a dev server) through a small proxy
  list                       running previews
  stop <id>|all

It binds to this machine's Tailscale address only (never 0.0.0.0, never a public tunnel): whoever is on the tailnet
can open the link, nobody else can. No accounts, logins, allowlists or admin rights.
State lives in memory/local/ (previews.json, previews/<id>.log|.pid). Output is short: it goes into the agent's context.
"""
import argparse
import http.client
import http.server
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from functools import partial

HEALTH = "/__preview_health"
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade"}
PORTS = range(8800, 8900)
NO_TAILSCALE = ("Tailscale is not active on this machine, so there is no private link to give. Options: open it in "
                "Orca's browser (`orca tab create --url http://127.0.0.1:<port>/ --worktree active`), or on your "
                "computer: ssh -N -L <port>:127.0.0.1:<port> <user>@<this-server>. Never a public tunnel.")


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


# ---------- Tailscale (read-only: no login, no admin rights) ----------

def _run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def tailnet():
    """(ip, dns_name) of this machine on the tailnet, or (None, None) if Tailscale isn't up."""
    env_ip = os.environ.get("AGATE_PREVIEW_IP")  # tests, or a machine with several tailnets
    if env_ip:
        return env_ip, os.environ.get("AGATE_PREVIEW_HOST") or None
    code, out = _run(["tailscale", "ip", "-4"])
    ip = out.split()[0] if code == 0 and out.split() else None
    if not ip:
        return None, None
    host = None
    code, out = _run(["tailscale", "status", "--json"])
    if code == 0:
        try:
            host = ((json.loads(out).get("Self") or {}).get("DNSName") or "").rstrip(".") or None
        except ValueError:
            host = None
    return ip, host


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def kill(pid):
    if alive(pid):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass


def free_port(ip, taken=()):
    for port in PORTS:
        if port in taken:
            continue
        s = socket.socket()
        try:
            s.bind((ip, port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    return None


# ---------- the preview server (static folder or streaming proxy) ----------

class _Handler(http.server.SimpleHTTPRequestHandler):
    upstream = None

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def end_headers(self):
        if not self.upstream:
            self.send_header("Cache-Control", "no-store")  # edits show up on reload
        super().end_headers()

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
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() != "host"}
        local = "127.0.0.1:%d" % self.upstream
        origin = self.headers.get("Origin") or ""
        if origin.split("//", 1)[-1].lower() == (self.headers.get("Host") or "").lower():
            headers["Origin"] = "http://" + local  # same-origin stays same-origin behind the proxy
        headers["Host"] = local  # local servers that check Host (dev servers, agate serve) keep working
        conn = http.client.HTTPConnection("127.0.0.1", self.upstream, timeout=120)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
        except OSError as e:
            msg = ("502: local server 127.0.0.1:%d not answering (%s)\n" % (self.upstream, e)).encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            conn.close()
            return
        self.send_response(resp.status, resp.reason)
        sized = False
        for k, v in resp.getheaders():
            if k.lower() in HOP:
                continue
            sized = sized or k.lower() == "content-length"
            self.send_header(k, v)
        if not sized:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        try:
            while self.command != "HEAD":
                chunk = resp.read1(65536)  # streams Server-Sent Events (live view) as they come
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError:
            pass
        finally:
            conn.close()

    def _dispatch(self, static):
        if self.path.split("?", 1)[0] == HEALTH:
            return self._health()
        if self.upstream:
            return self._proxy()
        if static is None:
            return self.send_error(405)
        return static()

    def do_GET(self):
        self._dispatch(super().do_GET)

    def do_HEAD(self):
        self._dispatch(super().do_HEAD)

    def do_POST(self):
        self._dispatch(None)

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST


def make_server(ip, port, directory=None, upstream=None):
    handler_cls = type("PreviewHandler", (_Handler,), {"upstream": upstream})
    handler = partial(handler_cls, directory=directory or os.getcwd())
    srv = http.server.ThreadingHTTPServer((ip, port), handler)
    srv.daemon_threads = True
    return srv


def wait_health(ip, port, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen("http://%s:%d%s" % (ip, port, HEALTH), timeout=1) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.1)
    return False


# ---------- start / stop (also used by the hub apps) ----------

def start(root, directory=None, upstream=None, path=""):
    """Start a preview. Returns (entry, error). entry["url"] is the link to give the person."""
    ip, host = tailnet()
    if not ip:
        return None, NO_TAILSCALE
    items = [e for e in load_registry(root) if alive(e.get("pid"))]
    port = free_port(ip, {e.get("port") for e in items})
    if port is None:
        return None, "no free port in %d-%d on %s" % (PORTS.start, PORTS.stop - 1, ip)
    entry_id = time.strftime("p%m%d%H%M%S")
    sd = state_dir(root)
    log_path = os.path.join(sd, "previews", entry_id + ".log")
    cmd = [sys.executable, os.path.abspath(__file__), "_serve", "--ip", ip, "--port", str(port)]
    cmd += ["--dir", os.path.abspath(directory)] if directory else ["--upstream", str(upstream)]
    with open(log_path, "ab") as log:
        p = subprocess.Popen(cmd, cwd=root, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    if not wait_health(ip, port):
        kill(p.pid)
        return None, "the preview server didn't start; see " + log_path
    path = path.lstrip("/")
    entry = {"id": entry_id, "pid": p.pid, "ip": ip, "port": port,
             "target": os.path.abspath(directory) if directory else "port %d" % upstream,
             "url": "http://%s:%d/%s" % (host or ip, port, path),
             "ip_url": "http://%s:%d/%s" % (ip, port, path), "created": time.strftime("%Y-%m-%d %H:%M")}
    save_registry(root, items + [entry])
    return entry, None


def stop(root, entry_id):
    items = load_registry(root)
    targets = items if entry_id == "all" else [e for e in items if e["id"] == entry_id]
    for e in targets:
        kill(e.get("pid"))
    save_registry(root, [e for e in items if e not in targets])
    return [e["id"] for e in targets]


# ---------- commands ----------

def cmd_detect(root, args):
    ip, host = tailnet()
    if not ip:
        print(NO_TAILSCALE)
        return 1
    print("tailscale: up · %s%s" % (ip, (" · " + host) if host else ""))
    print("links look like: http://%s:<port>/ (ports %d-%d)" % (host or ip, PORTS.start, PORTS.stop - 1))
    return 0


def cmd_serve(root, args):
    target, path = args.target, ""
    if not target and not args.port:
        print("give a file, a folder or --port N", file=sys.stderr)
        return 2
    if target:
        if os.path.isfile(target):
            target, path = os.path.dirname(os.path.abspath(target)), os.path.basename(target)
        elif not os.path.isdir(target):
            print("not found: %s" % target, file=sys.stderr)
            return 2
    entry, err = start(root, directory=target, upstream=args.port, path=args.path or path)
    if err:
        print(err, file=sys.stderr)
        return 1
    print("link (tailnet only): " + entry["url"])
    if entry["url"] != entry["ip_url"]:
        print("same, by IP: " + entry["ip_url"])
    print("id %s · stop it with `preview.py stop %s`" % (entry["id"], entry["id"]))
    return 0


def cmd_list(root, args):
    items = load_registry(root)
    if not items:
        print("no previews")
        return 0
    for e in items:
        print("%s  %-7s %s  %s" % (e["id"], "running" if alive(e.get("pid")) else "stopped", e.get("url"),
                                   e.get("target", "")))
    return 0


def cmd_stop(root, args):
    done = stop(root, args.id)
    if not done:
        print("no preview %s" % args.id, file=sys.stderr)
        return 2
    print("stopped " + ", ".join(done))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="preview.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect")
    s = sub.add_parser("serve")
    s.add_argument("target", nargs="?", help="a file or folder")
    s.add_argument("--port", type=int, help="share a local server on this port")
    s.add_argument("--path", default="", help="page to open in the link (e.g. artifacts/x.html)")
    sub.add_parser("list")
    st = sub.add_parser("stop")
    st.add_argument("id")
    i = sub.add_parser("_serve")
    i.add_argument("--ip", required=True)
    i.add_argument("--port", type=int, required=True)
    i.add_argument("--dir")
    i.add_argument("--upstream", type=int)
    args = ap.parse_args(argv)
    if args.cmd == "_serve":
        srv = make_server(args.ip, args.port, directory=args.dir, upstream=args.upstream)
        try:
            srv.serve_forever()
        finally:
            srv.server_close()
        return 0
    root = find_root()
    return {"detect": cmd_detect, "serve": cmd_serve, "list": cmd_list, "stop": cmd_stop}[args.cmd](root, args)


if __name__ == "__main__":
    sys.exit(main())
