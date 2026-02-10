from __future__ import annotations

from django.conf import settings

from .orm import ORMPortalGateway
from .sql import SQLPortalGateway


def get_portal_gateway():
    backend = getattr(settings, "PORTAL_GATEWAY_BACKEND", "orm").strip().lower()
    if backend == "orm":
        return ORMPortalGateway(alias=getattr(settings, "PORTAL_DB_ALIAS", "portal"))
    if backend == "sql":
        return SQLPortalGateway()
    raise ValueError(f"Unsupported PORTAL_GATEWAY_BACKEND: {backend}")
