from __future__ import annotations

from app.services.external_sources.registry import get_provider, register_provider
from app.services.external_sources.mcy_shop import (
    MCY_SHOP_PROVIDER,
    create_mcy_shop_provider,
)
from app.services.external_sources.standard_http import (
    STANDARD_HTTP_PROVIDER,
    create_standard_http_provider,
)


def register_builtin_external_providers() -> None:
    if get_provider(MCY_SHOP_PROVIDER) is None:
        register_provider(create_mcy_shop_provider())
    if get_provider(STANDARD_HTTP_PROVIDER) is None:
        register_provider(create_standard_http_provider())
