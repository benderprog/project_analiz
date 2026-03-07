from __future__ import annotations

from django.http import HttpRequest

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
    return {
        "ui_mode": ui_mode,
        "is_ui_admin": is_ui_admin,
    }
