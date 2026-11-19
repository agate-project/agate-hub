"""Built-in providers for remote-preview, plus project-added ones (.agate/project/preview.py, once approved)."""
from .base import PRIVACY_ORDER, Provider, ProviderError, choose, order_key  # noqa: F401


def builtin():
    from . import cloudflare_access, cloudflare_quick, orca, ssh, tailscale
    return [tailscale.PROVIDER, cloudflare_access.PROVIDER, orca.PROVIDER, ssh.PROVIDER, cloudflare_quick.PROVIDER]
