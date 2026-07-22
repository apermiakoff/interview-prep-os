"""Provider adapter factory.

All supported hosted and local protocols are normalized by HTTPGateway. Keeping
this module dependency-free makes it safe for the isolated worker to import.
"""

from app.ai.config import AIConfig
from app.ai.gateway import Gateway, HTTPGateway


def provider_gateway(config: AIConfig) -> Gateway:
    return HTTPGateway(config)


__all__ = ["provider_gateway"]
