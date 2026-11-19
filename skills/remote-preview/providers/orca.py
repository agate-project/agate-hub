"""Orca: when the agent runs inside Orca, Orca detects listening ports and its built-in browser may reach them.

No expose action: it only reports what Orca sees. Whether Orca's browser reaches a remote host's localhost
depends on how Orca is connected; check it once and note the result in memory/local/.
"""
import json
import shutil

from . import base
from .base import Provider


def orca_ports():
    if not shutil.which("orca"):
        return None
    code, out, _ = base.run(["orca", "ports", "--json"], timeout=8)
    if code != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


class Orca(Provider):
    name = "orca"
    privacy = "private"
    rank = 30
    identity_header = None
    manual = True

    def available(self):
        if not shutil.which("orca"):
            return False, "orca CLI not found"
        return True, ""

    def expose(self, local_port, ctx):
        return {"url": "http://127.0.0.1:%d/" % local_port, "handle": {},
                "note": "Open the URL in Orca's built-in browser (Shift+Ctrl+Click on the link). If it doesn't load, "
                        "Orca's browser can't reach this machine: use another provider."}


PROVIDER = Orca()
