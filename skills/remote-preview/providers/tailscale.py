"""Tailscale: `tailscale serve` (tailnet only). Never Funnel."""
import json
import shutil

from . import base
from .base import Provider, ProviderError

PORT_RANGE = range(8444, 8500)
PERMISSION_HINTS = ("permission", "access denied", "operation not permitted", "must be root", "sudo", "not allowed")


def _status():
    code, out, _ = base.run(["tailscale", "status", "--json"], timeout=10)
    if code != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def used_https_ports():
    """Ports already taken by `tailscale serve` (so we never overwrite someone else's)."""
    code, out, _ = base.run(["tailscale", "serve", "status", "--json"], timeout=10)
    ports = set()
    if code != 0 or not out.strip():
        return ports
    try:
        data = json.loads(out)
    except ValueError:
        return ports
    for key in (data.get("TCP") or {}):
        if str(key).isdigit():
            ports.add(int(key))
    for hostport in (data.get("Web") or {}):
        tail = str(hostport).rsplit(":", 1)[-1]
        if tail.isdigit():
            ports.add(int(tail))
    return ports


def _looks_like_permission(err):
    e = (err or "").lower()
    return any(h in e for h in PERMISSION_HINTS)


def run_privileged(cmd):
    """Run cmd; on a permission error retry with `sudo -n`. Returns (ok, used_cmd, manual_cmd_or_None, err)."""
    code, _, err = base.run(cmd)
    if code == 0:
        return True, cmd, None, ""
    if _looks_like_permission(err) and shutil.which("sudo"):
        scmd = ["sudo", "-n"] + cmd
        code2, _, err2 = base.run(scmd)
        if code2 == 0:
            return True, scmd, None, ""
        return False, None, "sudo " + " ".join(cmd), err2 or err
    return False, None, None, err


class Tailscale(Provider):
    name = "tailscale"
    # A tailnet alone is "network"; with the identity allowlist enforced by the preview server it is private.
    privacy = "private"
    rank = 10
    identity_header = "Tailscale-User-Login"

    def available(self):
        if not shutil.which("tailscale"):
            return False, "tailscale is not installed"
        st = _status()
        if not st:
            return False, "tailscale status failed"
        if st.get("BackendState") != "Running":
            return False, "tailscale is not running (%s)" % st.get("BackendState")
        return True, ""

    def hostname(self):
        st = _status() or {}
        return ((st.get("Self") or {}).get("DNSName") or "").rstrip(".")

    def expose(self, local_port, ctx):
        used = used_https_ports()
        https = next((p for p in PORT_RANGE if p not in used), None)
        if https is None:
            raise ProviderError("no free https port in %d-%d" % (PORT_RANGE.start, PORT_RANGE.stop - 1))
        cmd = ["tailscale", "serve", "--bg", "--https=%d" % https, "http://127.0.0.1:%d" % local_port]
        ok, used_cmd, manual, err = run_privileged(cmd)
        handle = {"https_port": https}
        if not ok:
            if manual:
                return {"url": None, "handle": handle, "manual": manual,
                        "note": "Needs admin rights. Ask the person to run: " + manual}
            raise ProviderError("tailscale serve failed: " + (err or "").strip())
        handle["sudo"] = used_cmd[0] == "sudo"
        host = self.hostname()
        url = "https://%s:%d/" % (host, https) if host else None
        return {"url": url, "handle": handle, "note": "tailnet only; the preview server enforces the allowlist"}

    def stop(self, handle):
        if not handle or "https_port" not in handle:
            return
        cmd = ["tailscale", "serve", "--https=%d" % handle["https_port"], "off"]
        ok, _, manual, err = run_privileged(cmd)
        if not ok:
            raise ProviderError(("run: " + manual) if manual else ("tailscale serve off failed: " + err))


PROVIDER = Tailscale()
