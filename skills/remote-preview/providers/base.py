"""Provider interface for remote-preview.

A provider publishes a local port (127.0.0.1:<port>) so the person can open it from their own device.

Attributes:
    name             id used on the command line (--via <name>)
    privacy          "private" (only the person), "network" (everyone on a network) or "public" (anyone with the link)
    rank             order among providers with the same privacy (lower first)
    identity_header  HTTP header the provider adds with the viewer's identity, or None if it adds none
    manual           True if expose() only returns instructions (the person runs something)

Methods:
    available() -> (bool, str)              whether it can be used here, and why not
    expose(local_port, ctx) -> dict         {"url": ..., "handle": {...}, "note": ...}; may raise ProviderError
    stop(handle) -> None
"""

import subprocess

PRIVACY_ORDER = {"private": 0, "network": 1, "public": 2}


def run(cmd, timeout=20):
    """Run a command; returns (returncode, stdout, stderr). Never raises for a missing binary."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


class ProviderError(Exception):
    pass


class Provider:
    name = "base"
    privacy = "private"
    rank = 50
    identity_header = None
    manual = False

    def available(self):
        return False, "not implemented"

    def expose(self, local_port, ctx):
        raise ProviderError("not implemented")

    def stop(self, handle):
        return None


def order_key(provider):
    return (PRIVACY_ORDER.get(provider.privacy, 9), provider.rank, provider.name)


def choose(providers, allow_public=False):
    """Most private available provider. Public ones only with allow_public."""
    usable = []
    for p in sorted(providers, key=order_key):
        ok, _ = p.available()
        if not ok:
            continue
        if p.privacy == "public" and not allow_public:
            continue
        usable.append(p)
    return usable[0] if usable else None
