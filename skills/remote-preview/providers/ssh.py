"""SSH local forward: private (SSH authenticates the person). Only prints the command the person runs."""
import getpass
import os
import socket

from .base import Provider


def ssh_target():
    user = os.environ.get("USER") or getpass.getuser()
    conn = os.environ.get("SSH_CONNECTION", "").split()
    host = conn[2] if len(conn) >= 3 else socket.getfqdn()
    return user, host


class SSH(Provider):
    name = "ssh"
    privacy = "private"
    rank = 40
    identity_header = None
    manual = True

    def available(self):
        return True, ""

    def expose(self, local_port, ctx):
        user, host = ssh_target()
        cmd = "ssh -N -L %d:127.0.0.1:%d %s@%s" % (local_port, local_port, user, host)
        return {"url": "http://127.0.0.1:%d/" % local_port, "handle": {}, "manual": cmd,
                "note": "The person runs this on their own computer, then opens the URL there: " + cmd}


PROVIDER = SSH()
