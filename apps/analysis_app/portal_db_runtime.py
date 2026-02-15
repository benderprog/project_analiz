from __future__ import annotations

from django.db import connections

from apps.analysis_app.models import PortalDbConnectionSettings
from apps.analysis_app.utils.portal_db_crypto import decrypt_password


def get_portal_settings_singleton() -> PortalDbConnectionSettings | None:
    return PortalDbConnectionSettings.objects.order_by("id").first()


def build_django_db_settings(db_obj: PortalDbConnectionSettings) -> dict:
    options = {}
    if db_obj.profile == PortalDbConnectionSettings.Profile.PROD:
        options = {"options": "-c default_transaction_read_only=on"}
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": db_obj.db_name,
        "USER": db_obj.user,
        "PASSWORD": decrypt_password(db_obj.password_encrypted),
        "HOST": db_obj.host,
        "PORT": str(db_obj.port),
        "OPTIONS": options,
    }


def _same_connection_settings(current: dict, desired: dict) -> bool:
    keys = ("ENGINE", "NAME", "USER", "PASSWORD", "HOST", "PORT", "OPTIONS")
    return all((current.get(key) or {}) == (desired.get(key) or {}) for key in keys)


def apply_portal_db_settings() -> None:
    db_obj = get_portal_settings_singleton()
    if not db_obj:
        return

    desired = build_django_db_settings(db_obj)
    current = connections.databases.get("portal", {})

    if _same_connection_settings(current, desired):
        return

    merged = {**current, **desired}
    connections.databases["portal"] = merged
    if "portal" in connections:
        connections["portal"].close()
