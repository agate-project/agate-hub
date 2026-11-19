"""Cloudflare Tunnel + Cloudflare Access: private by email. Needs cloudflared and a named tunnel."""
import os
import shutil
import subprocess

from .base import Provider, ProviderError

SETUP = (
    "Cloudflare Access needs a one-time setup: a Cloudflare account with a domain, `cloudflared tunnel login`, "
    "`cloudflared tunnel create <name>`, a DNS route (`cloudflared tunnel route dns <name> <hostname>`) and an "
    "Access application on that hostname allowing only the person's email. Then set AGATE_CF_TUNNEL=<name> and "
    "AGATE_CF_HOSTNAME=<hostname> in .env."
)


class CloudflareAccess(Provider):
    name = "cloudflare-access"
    privacy = "private"
    rank = 20
    identity_header = "Cf-Access-Authenticated-User-Email"

    def available(self):
        if not shutil.which("cloudflared"):
            return False, "cloudflared is not installed. " + SETUP
        if not (os.environ.get("AGATE_CF_TUNNEL") and os.environ.get("AGATE_CF_HOSTNAME")):
            return False, "no named tunnel configured. " + SETUP
        return True, ""

    def expose(self, local_port, ctx):
        ok, why = self.available()
        if not ok:
            raise ProviderError(why)
        tunnel, host = os.environ["AGATE_CF_TUNNEL"], os.environ["AGATE_CF_HOSTNAME"]
        log = open(ctx["log_path"], "ab") if ctx.get("log_path") else subprocess.DEVNULL
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "run", "--url", "http://127.0.0.1:%d" % local_port, tunnel],
            stdout=log, stderr=log, start_new_session=True)
        return {"url": "https://%s/" % host, "handle": {"pid": proc.pid},
                "note": "only emails allowed by the Access policy can open it"}

    def stop(self, handle):
        from .proc import kill
        if handle and handle.get("pid"):
            kill(handle["pid"])


PROVIDER = CloudflareAccess()
