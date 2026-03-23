from __future__ import annotations

import os

from django.conf import settings
from django.db import connections

from apps.analysis_app.models import PortalDbConnectionSettings
from apps.analysis_app.utils.portal_db_crypto import decrypt_password


def get_portal_settings_singleton() -> PortalDbConnectionSettings | None:
    return PortalDbConnectionSettings.objects.order_by("id").first()


def resolve_portal_password(
    db_obj: PortalDbConnectionSettings,
    current_settings: dict | None = None,
) -> str:
    current_settings = current_settings or {}
    env_password = os.getenv("PORTAL_DB_PASSWORD", "")
    current_password = current_settings.get("PASSWORD")

    if not db_obj.password_encrypted:
        return env_password or current_password or ""

    try:
        decrypted_password = decrypt_password(db_obj.password_encrypted)
    except Exception:  # noqa: BLE001
        return env_password or current_password or ""

    return decrypted_password or env_password or current_password or ""


def build_django_db_settings(db_obj: PortalDbConnectionSettings, current_settings: dict) -> dict:
    options = {}
    if db_obj.profile == PortalDbConnectionSettings.Profile.PROD:
        options = {"options": "-c default_transaction_read_only=on"}
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": db_obj.db_name,
        "USER": db_obj.user,
        "PASSWORD": resolve_portal_password(db_obj, current_settings),
        "HOST": db_obj.host,
        "PORT": str(db_obj.port),
        "OPTIONS": options,
    }


def _resolve_runtime_sql_profile(db_profile: str) -> str:
    if db_profile == PortalDbConnectionSettings.Profile.PROD:
        return "prod_ro"
    return "dev"


def _same_connection_settings(current: dict, desired: dict) -> bool:
    keys = ("ENGINE", "NAME", "USER", "PASSWORD", "HOST", "PORT")
    if not all(current.get(key) == desired.get(key) for key in keys):
        return False
    return (current.get("OPTIONS") or {}) == (desired.get("OPTIONS") or {})


def _reset_django_connection(alias: str, cfg: dict) -> None:
    for connection in connections.all(initialized_only=True):
        if connection.alias != alias:
            continue
        connection.close()
        connection.settings_dict.update(cfg)
        return


def apply_portal_db_settings() -> None:
    db_obj = get_portal_settings_singleton()
    if not db_obj:
        return

    current = connections.databases.get("portal", {})
    desired = build_django_db_settings(db_obj, current)

    os.environ["PORTAL_PROFILE"] = _resolve_runtime_sql_profile(db_obj.profile)

    if not desired.get("PASSWORD"):
        if current.get("PASSWORD") not in (None, ""):
            desired["PASSWORD"] = current["PASSWORD"]
        else:
            desired.pop("PASSWORD", None)

    if _same_connection_settings(current, desired):
        return

    merged = {**current, **desired}
    settings.DATABASES["portal"] = merged
    connections.databases["portal"] = merged
    _reset_django_connection("portal", merged)
