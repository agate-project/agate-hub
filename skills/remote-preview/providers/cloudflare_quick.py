"""Cloudflare quick tunnel (trycloudflare.com): PUBLIC. Anyone with the link can open it."""
import re
import shutil
import subprocess
import time

from .base import Provider, ProviderError

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class CloudflareQuick(Provider):
    name = "cloudflare-quick"
    privacy = "public"
    rank = 90
    identity_header = None

    def available(self):
        if not shutil.which("cloudflared"):
            return False, "cloudflared is not installed"
        return True, ""

    def expose(self, local_port, ctx):
        if not ctx.get("allow_public"):
            raise ProviderError("public provider: needs --i-understand-public and the person's explicit ok")
        ok, why = self.available()
        if not ok:
            raise ProviderError(why)
        log_path = ctx.get("log_path")
        log = open(log_path, "ab") if log_path else subprocess.DEVNULL
        proc = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://127.0.0.1:%d" % local_port],
                                stdout=log, stderr=log, start_new_session=True)
        url = None
        end = time.time() + 20
        while log_path and time.time() < end and url is None:
            time.sleep(0.5)
            try:
                m = URL_RE.search(open(log_path, errors="ignore").read())
                url = m.group(0) + "/" if m else None
            except OSError:
                pass
        return {"url": url, "handle": {"pid": proc.pid},
                "note": "PUBLIC: anyone with the link can open it. Stop it as soon as the person is done."}

    def stop(self, handle):
        from .proc import kill
        if handle and handle.get("pid"):
            kill(handle["pid"])


PROVIDER = CloudflareQuick()
