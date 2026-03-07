from __future__ import annotations

import os
import subprocess
from functools import lru_cache

from django.conf import settings
from django.http import HttpRequest
from django.db import DatabaseError

from apps.analysis_app.models import FeatureFlags, PortalDbConnectionSettings

UI_MODE_SESSION_KEY = "ui_mode"
UI_MODE_USER = "user"
UI_MODE_ADMIN = "admin"
UI_MODE_CHOICES = {UI_MODE_USER, UI_MODE_ADMIN}


def get_ui_mode(request: HttpRequest) -> str:
    """Return effective UI mode with staff-only enforcement."""
    mode = str(request.session.get(UI_MODE_SESSION_KEY, UI_MODE_USER)).strip().lower()
    if mode not in UI_MODE_CHOICES:
        mode = UI_MODE_USER
    if not (request.user.is_authenticated and request.user.is_staff):
        request.session[UI_MODE_SESSION_KEY] = UI_MODE_USER
        return UI_MODE_USER
    request.session[UI_MODE_SESSION_KEY] = mode
    return mode


def set_ui_mode(request: HttpRequest, mode: str) -> str:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in UI_MODE_CHOICES:
        normalized_mode = UI_MODE_USER
    if not (request.user.is_authenticated and request.user.is_staff):
        normalized_mode = UI_MODE_USER
    request.session[UI_MODE_SESSION_KEY] = normalized_mode
    return normalized_mode


def ui_mode_context(request: HttpRequest) -> dict[str, object]:
    ui_mode = get_ui_mode(request)
    is_ui_admin = ui_mode == UI_MODE_ADMIN and bool(request.user.is_authenticated and request.user.is_staff)

    debug_mode = False
    portal_mode = _portal_mode_label()
    try:
        debug_mode = FeatureFlags.is_effective_debug_enabled()
        db_settings = PortalDbConnectionSettings.objects.order_by("id").first()
        portal_mode = _portal_mode_label(db_settings)
    except DatabaseError:
        # Management commands and early bootstrap may not have migrated DB.
        pass

    return {
        "ui_mode": ui_mode,
        "is_ui_admin": is_ui_admin,
        "status_ui_label": "Admin" if is_ui_admin else "User",
        "status_portal_label": portal_mode,
        "status_debug_label": "ON" if debug_mode else "OFF",
        "status_version_label": _version_label(),
    }


def _portal_mode_label(db_settings: PortalDbConnectionSettings | None = None) -> str:
    mode = str(os.getenv("PORTAL_MODE", "")).strip().lower()
    if mode == "local":
        return "LOCAL"

    if db_settings:
        if db_settings.profile == PortalDbConnectionSettings.Profile.PROD:
            return "PROD RO"
        if db_settings.profile == PortalDbConnectionSettings.Profile.TEST:
            return "TEST RW"

    if mode == "remote":
        return "REMOTE"
    return "LOCAL"


@lru_cache(maxsize=1)
def _version_label() -> str:
    raw_version = str(os.getenv("VERSION") or getattr(settings, "VERSION", "")).strip()
    sha_value = _short_sha()
    if raw_version:
        normalized_version = raw_version if raw_version.lower().startswith("v") else f"v{raw_version}"
        return f"{normalized_version} ({sha_value})" if sha_value else normalized_version
    return sha_value or "dev"


def _short_sha() -> str:
    sha = str(os.getenv("GIT_SHA") or os.getenv("COMMIT_SHA") or os.getenv("SOURCE_VERSION") or "").strip()
    if sha:
        return sha[:7]
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True)
            .strip()
            .lower()
        )
    except Exception:  # noqa: BLE001
        return ""
