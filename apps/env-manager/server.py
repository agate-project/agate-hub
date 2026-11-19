"""env-manager local server: write-only, one-time link, CSRF, 127.0.0.1 only (stdlib).

Values arrive in a POST body and go straight to `agate.py env set NAME --stdin` (stdin only). Nothing ever sends an
existing value back: the page only sees names, status, owners and fingerprints from `env check --json --fingerprint`.
"""

import http.server
import json
import os
import re
import secrets
import threading
import time
from http import cookies
from urllib.parse import parse_qs, urlsplit

import launch

VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]{1,63}$")
MAX_BODY = 16 * 1024
HERE = os.path.dirname(os.path.abspath(__file__))
COOKIE = "agate_env"


def where_hints(root):
    """{NAME: "where to get it"} from the comments `add` writes in .env.example (`# <for>: <where>`)."""
    out, last = {}, None
    try:
        with open(os.path.join(root, ".env.example"), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            last = s.lstrip("#").strip()
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=", s)
        if m and last and ":" in last:
            out[m.group(1)] = last.split(":", 1)[1].strip()
        last = None
    return out


class State:
    def __init__(self, root, focus=None, mode="local", identity_header=None, allow=(), hosts=(),
                 idle_timeout=600, lang="", on_event=print, agate=launch.run_agate, package=""):
        self.root = root
        self.package = package
        self.focus = [n for n in (focus or []) if VAR_RE.match(n)]
        self.mode = mode
        self.identity_header = identity_header
        self.allow = tuple(a.lower() for a in allow)
        self.hosts = set(hosts)
        self.idle_timeout = idle_timeout
        self.lang = lang
        self.on_event = on_event
        self.agate = agate
        self.token = secrets.token_urlsafe(32)
        self.token_used = False
        self.created = time.time()
        self.ttl = idle_timeout
        self.session = None
        self.csrf = secrets.token_urlsafe(24)
        self.last = time.time()
        self.saved = []
        self.lock = threading.Lock()
        self.server = None

    # -- data the page may see (never values)
    def status(self):
        rc, out, _ = self.agate(self.root, ["env", "check", "--json", "--fingerprint"] + self.focus)
        try:
            report = json.loads(out)
        except ValueError:
            report = {"vars": [], "alerts": ["env check failed"]}
        hints = where_hints(self.root)
        keep = ("name", "status", "used_by", "fp", "format", "issues", "live")
        rows = [{k: r[k] for k in keep if k in r} for r in report.get("vars", [])]
        for r in rows:
            r["where"] = hints.get(r["name"], "")
        known = {r["name"] for r in rows}
        for n in self.focus:
            if n not in known:
                rows.append({"name": n, "status": "missing", "used_by": [], "where": hints.get(n, ""),
                             "issues": []})
        return {"vars": rows, "alerts": report.get("alerts", [])}

    def allowed_names(self):
        rc, out, _ = self.agate(self.root, ["env", "check", "--json"])
        try:
            names = {r["name"] for r in json.loads(out).get("vars", [])}
        except ValueError:
            names = set()
        return names | set(self.focus)

    def consent_given(self):
        c = launch.preferences(self.root).get("consents")
        return isinstance(c, dict) and bool(c.get("env_manager"))

    def give_consent(self):
        launch.set_nested(launch.prefs_path(self.root), "consents", "env_manager", launch.today())

    def save(self, name, value):
        rc, out, err = self.agate(self.root, ["env", "set", name, "--stdin"], stdin=value + "\n")
        m = re.search(r"saved: %s \(fp:([0-9a-f]{6})\)" % re.escape(name), out or "")
        if rc != 0 or not m:
            return None, "not saved"
        fp = m.group(1)
        rc2, out2, _ = self.agate(self.root, ["env", "check", "--live", "--json", name], timeout=40)
        live = ""
        try:
            for r in json.loads(out2).get("vars", []):
                if r.get("name") == name:
                    live = r.get("live", "")
        except ValueError:
            pass
        verified = "ok" if live == "ok" else ("rejected" if str(live).startswith("rejected") else "unchecked")
        mark = {"ok": "✓", "rejected": "✗", "unchecked": "–"}[verified]
        self.saved.append(name)
        self.on_event("saved: %s (fp:%s) · verified %s" % (name, fp, mark))
        return {"name": name, "fp": fp, "verified": verified}, ""

    def shutdown(self):
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


def page(state, nonce):
    with open(os.path.join(HERE, "ui", "index.html"), encoding="utf-8") as f:
        tpl = f.read()
    boot = {"lang": state.lang, "csrf": state.csrf, "mode": state.mode, "focus": state.focus,
            "package": state.package, "consent": state.consent_given()}
    return tpl.replace("__NONCE__", nonce).replace("__BOOT__", json.dumps(boot).replace("<", "\\u003c"))


ERRORS = {
    "en": {"403_t": "You don't have access to this link",
           "403_b": "This link is only for {allowed}. Tailscale identified you as {who}.",
           "403_n": "The attempt was recorded and reported in the chat.",
           "410_t": "This link no longer works",
           "410_b": "It was used or it expired (10 minutes). Ask the agent for a new link.",
           "nolink_t": "Open the link the agent gave you", "nolink_b": "Each link works once."},
    "es": {"403_t": "No tienes acceso a este enlace",
           "403_b": "Este enlace es solo para {allowed}. Tailscale te identificó como {who}.",
           "403_n": "El intento queda registrado y se avisa en el chat.",
           "410_t": "Este enlace ya no sirve",
           "410_b": "Se usó o venció (10 minutos). Para pegar el valor, pídele al agente un enlace nuevo.",
           "nolink_t": "Abre el enlace que te dio el agente", "nolink_b": "Cada enlace funciona una sola vez."},
}


def _mask(identity):
    user, _, dom = identity.partition("@")
    return (user[:6] + "…") if not dom else "%s@…" % user[:12]


def error_page(lang, code, title, body, note=""):
    import html as _h  # noqa: PLC0415
    return ("<!doctype html><html lang='%s'><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            "initial-scale=1'><title>%s</title><style>body{font:15px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;"
            "background:#F5F3EF;color:#1C1A17;margin:0;display:grid;place-items:center;min-height:100vh;padding:16px}"
            "@media(prefers-color-scheme:dark){body{background:#0A0D12;color:#EDEFF3}.c{background:#151a21;"
            "border-color:#2a313a}}.c{max-width:440px;background:#fff;border:1px solid #E5E0D8;border-radius:12px;"
            "padding:22px 24px}h1{font-size:18px;margin:0 0 8px}p{margin:0 0 8px}code{font:12px ui-monospace,"
            "monospace;color:#78716A}</style><div class='c'><h1>%s</h1><p>%s</p><p>%s</p><code>%s</code></div>"
            % (lang, _h.escape(title), _h.escape(title), _h.escape(body), _h.escape(note), _h.escape(code)))


class Handler(http.server.BaseHTTPRequestHandler):
    state = None  # set by make_server
    server_version = "agate-env"
    sys_version = ""

    def log_message(self, fmt, *args):  # method + path only: never query strings, bodies or headers
        pass

    # -- helpers
    def _headers(self, status, ctype, length, extra=None, nonce=""):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-%s'; connect-src 'self'; "
                         "img-src data:; form-action 'none'; frame-ancestors 'none'; base-uri 'none'" % nonce)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _send(self, status, body, ctype="text/plain; charset=utf-8", extra=None, nonce=""):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self._headers(status, ctype, len(data), extra, nonce)
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _strings(self):
        return ERRORS.get(self.state.lang, ERRORS["en"])

    def _forbidden(self):
        st, t = self.state, self._strings()
        who = (self.headers.get(st.identity_header) or "").strip().lower() if st.identity_header else ""
        if who:
            st.on_event("blocked: access attempt from %s (not in the allowlist)" % who)
        allowed = ", ".join(_mask(a) for a in st.allow) or "?"
        body = error_page(st.lang or "en", "403 · identity not in allowlist", t["403_t"],
                          t["403_b"].format(allowed=allowed, who=who or "?"), t["403_n"])
        return self._send(403, body, "text/html; charset=utf-8")

    def _gone(self):
        t = self._strings()
        return self._send(410, error_page(self.state.lang or "en", "410 · link used or expired", t["410_t"],
                                          t["410_b"]), "text/html; charset=utf-8")

    def _identity_ok(self):
        st = self.state
        if not st.identity_header:
            return True
        who = (self.headers.get(st.identity_header) or "").strip().lower()
        return bool(who) and who in st.allow

    def _host_ok(self):
        if not self.state.hosts:
            return True
        host = (self.headers.get("Host") or "").lower()
        return host in self.state.hosts or host.split(":")[0] in self.state.hosts

    def _session_ok(self):
        raw = self.headers.get("Cookie") or ""
        c = cookies.SimpleCookie()
        try:
            c.load(raw)
        except cookies.CookieError:
            return False
        st = self.state
        return bool(st.session) and COOKIE in c and secrets.compare_digest(c[COOKIE].value, st.session)

    def _touch(self):
        self.state.last = time.time()

    # -- routes
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/healthz":
            return self._send(200, "ok\n")
        if not self._host_ok():
            return self._send(403, "403: not allowed\n")
        if not self._identity_ok():
            return self._forbidden()
        st = self.state
        if path == "/":
            token = (parse_qs(query).get("t") or [""])[0]
            if token:
                with st.lock:
                    expired = time.time() - st.created > st.ttl
                    if st.token_used or expired or not secrets.compare_digest(token, st.token):
                        return self._gone()
                    st.token_used = True
                    st.session = secrets.token_urlsafe(32)
                secure = "; Secure" if st.mode == "tailscale" else ""
                self._touch()
                return self._send(303, "", extra={
                    "Location": "/", "Set-Cookie": "%s=%s; HttpOnly; SameSite=Strict; Path=/%s"
                                                    % (COOKIE, st.session, secure)})
            if not self._session_ok():
                t = self._strings()
                return self._send(403, error_page(st.lang or "en", "403", t["nolink_t"], t["nolink_b"]),
                                  "text/html; charset=utf-8")
            self._touch()
            nonce = secrets.token_urlsafe(16)
            return self._send(200, page(st, nonce), "text/html; charset=utf-8", nonce=nonce)
        if path == "/api/status":
            if not self._session_ok():
                return self._send(403, "403\n")
            self._touch()
            return self._json(200, st.status())
        return self._send(404, "404\n")

    do_HEAD = do_GET

    def do_POST(self):
        path = urlsplit(self.path).path
        if not self._host_ok() or not self._session_ok():
            return self._send(403, "403: not allowed\n")
        if not self._identity_ok():
            return self._forbidden()
        st = self.state
        if not secrets.compare_digest(self.headers.get("X-CSRF") or "", st.csrf):
            return self._send(403, "403: bad request token\n")
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
            return self._send(403, "403: cross-origin request\n")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, "413\n")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, "400\n")
        self._touch()
        if path == "/api/consent":
            st.give_consent()
            return self._json(200, {"ok": True})
        if path == "/api/done":
            self._json(200, {"ok": True})
            return st.shutdown()
        if path == "/api/verify":
            name = str(body.get("name", ""))
            if not VAR_RE.match(name) or name not in st.allowed_names():
                return self._json(400, {"error": "unknown variable"})
            rc, out, _ = st.agate(st.root, ["env", "check", "--live", "--json", name], timeout=40)
            try:
                live = next((r.get("live", "") for r in json.loads(out).get("vars", [])
                             if r.get("name") == name), "")
            except ValueError:
                live = ""
            return self._json(200, {"name": name, "live": live or "no live check"})
        if path == "/api/save":
            if not st.consent_given():
                return self._json(409, {"error": "consent required"})
            values = body.get("values") if isinstance(body.get("values"), dict) else {}
            body["values"] = None  # drop our reference as soon as possible
            allowed = st.allowed_names()
            todo = []
            for name, value in values.items():
                value = str(value or "").strip()
                if not value:
                    continue
                if not VAR_RE.match(str(name)) or name not in allowed:
                    return self._json(400, {"error": "unknown variable"})
                if len(value) > 8192 or "\n" in value:
                    return self._json(400, {"error": "invalid value", "name": name})
                todo.append((name, value))
            values = None
            if not todo:
                return self._json(400, {"error": "nothing to save"})
            results = []
            for name, value in todo:
                result, err = st.save(name, value)
                results.append(result or {"name": name, "error": err})
            todo = None
            self._json(200, {"results": results})
            if not body.get("continue"):
                st.shutdown()
            return None
        if path in ("/api/add", "/api/remove"):
            if st.focus:
                return self._json(403, {"error": "only in the manage-all view"})
            name = str(body.get("name", ""))
            if not VAR_RE.match(name):
                return self._json(400, {"error": "invalid name"})
            if path == "/api/add":
                args = ["env", "add", name]
                if body.get("where"):
                    args += ["--where", str(body["where"])[:200]]
                if body.get("for"):
                    args += ["--for", str(body["for"])[:80]]
                rc, out, _ = st.agate(st.root, args)
                st.on_event("added: %s" % name if rc == 0 else "add failed: %s" % name)
                return self._json(200 if rc == 0 else 500, {"name": name, "ok": rc == 0})
            if name not in st.allowed_names():
                return self._json(400, {"error": "unknown variable"})
            rc, out, _ = st.agate(st.root, ["env", "remove", name, "--yes", "--clear-local"])
            st.on_event("removed: %s" % name if rc == 0 else "remove failed: %s" % name)
            return self._json(200 if rc == 0 else 500, {"name": name, "ok": rc == 0})
        return self._send(404, "404\n")


def make_server(state, port=0):
    handler = type("EnvHandler", (Handler,), {"state": state})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    srv.daemon_threads = True
    state.server = srv
    return srv


def watchdog(state, interval=1.0):
    """Shut down after `idle_timeout` seconds without requests."""
    def loop():
        while state.server is not None:
            if time.time() - state.last > state.idle_timeout:
                state.on_event("env-manager: closed after %d min without activity" % (state.idle_timeout // 60))
                state.server.shutdown()
                return
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
