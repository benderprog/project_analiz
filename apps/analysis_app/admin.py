from django.contrib import admin, messages
from django.core.management import call_command
from django.db import connections
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils import timezone

import psycopg2

from apps.analysis_app.admin_forms import PortalDbConnectionSettingsAdminForm
from apps.analysis_app.models import (
    CachedPU,
    CachedSubdivision,
    CachedSubdivisionAlias,
    PortalDbConnectionSettings,
    SvodkaTemplate,
)
from apps.analysis_app.pu_cache import upsert_pu_cache
from apps.analysis_app.portal_records import PortalPURecord
from apps.analysis_app.portal_db_runtime import apply_portal_db_settings, resolve_portal_password
from apps.analysis_app.portal_db_settings_service import get_test_portal_db_params
from apps.analysis_app.utils.portal_db_crypto import encrypt_password
from apps.portaldb.gateway import get_portal_gateway


@admin.action(description="Rebuild embeddings")
def rebuild_subdivision_embeddings(modeladmin, request, queryset):
    call_command("sync_portal_reference", rebuild_embeddings=True)


@admin.register(PortalDbConnectionSettings)
class PortalDbConnectionSettingsAdmin(admin.ModelAdmin):
    form = PortalDbConnectionSettingsAdminForm
    change_form_template = "admin/analysis_app/portaldbconnectionsettings/change_form.html"
    list_display = ("profile", "host", "db_name", "last_check_ok", "last_check_at")
    readonly_fields = (
        "state_display",
        "access_mode_display",
        "last_check_ok",
        "last_check_error",
        "last_check_at",
    )
    fieldsets = (
        (
            "Параметры подключения",
            {"fields": ("host", "port", "db_name", "user", "password", "profile")},
        ),
        (
            "Состояние базы данных",
            {
                "fields": (
                    "state_display",
                    "access_mode_display",
                    "last_check_ok",
                    "last_check_at",
                    "last_check_error",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return not PortalDbConnectionSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = PortalDbConnectionSettings.objects.order_by("id").first()
        if obj:
            url = reverse("admin:analysis_app_portaldbconnectionsettings_change", args=[obj.pk])
            return redirect(url)
        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/check-connection/",
                self.admin_site.admin_view(self.check_connection_view),
                name="analysis_app_portaldbconnectionsettings_check_connection",
            ),
            path(
                "<path:object_id>/use-test-db/",
                self.admin_site.admin_view(self.use_test_db_view),
                name="analysis_app_portaldbconnectionsettings_use_test_db",
            ),
        ]
        return custom_urls + urls

    @admin.display(description="Состояние")
    def state_display(self, obj):
        if obj.last_check_ok is True:
            return "Подключено"
        if obj.last_check_ok is False:
            return "Не доступно"
        return "Не проверялось"

    @admin.display(description="Режим доступа")
    def access_mode_display(self, obj):
        if obj.profile == PortalDbConnectionSettings.Profile.PROD:
            return "только чтение"
        return "чтение/запись"

    def save_model(self, request, obj, form, change):
        incoming_password = form.cleaned_data.get("password")
        if incoming_password:
            obj.password_encrypted = encrypt_password(incoming_password)
        elif change:
            existing = PortalDbConnectionSettings.objects.filter(pk=obj.pk).first()
            if existing:
                obj.password_encrypted = existing.password_encrypted
        super().save_model(request, obj, form, change)
        apply_portal_db_settings()

    def _connect_to_db(self, obj):
        current_portal_settings = connections.databases.get("portal", {})
        password = resolve_portal_password(obj, current_portal_settings)
        connect_kwargs = {
            "dbname": obj.db_name,
            "user": obj.user,
            "host": obj.host,
            "port": obj.port,
            "connect_timeout": 5,
        }
        if password not in (None, ""):
            connect_kwargs["password"] = password
        return psycopg2.connect(**connect_kwargs)

    def check_connection_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, "Настройка не найдена.", level=messages.ERROR)
            return redirect("admin:analysis_app_portaldbconnectionsettings_changelist")
        try:
            conn = self._connect_to_db(obj)
            conn.close()
            obj.last_check_ok = True
            obj.last_check_error = ""
            self.message_user(request, "Подключение успешно.", level=messages.SUCCESS)
        except Exception as exc:  # noqa: BLE001
            obj.last_check_ok = False
            obj.last_check_error = str(exc)
            self.message_user(request, f"Ошибка подключения: {exc}", level=messages.ERROR)
        obj.last_check_at = timezone.now()
        obj.save(update_fields=["last_check_ok", "last_check_error", "last_check_at", "updated_at"])
        return redirect(
            "admin:analysis_app_portaldbconnectionsettings_change",
            object_id,
        )

    def use_test_db_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, "Настройка не найдена.", level=messages.ERROR)
            return redirect("admin:analysis_app_portaldbconnectionsettings_changelist")
        params = get_test_portal_db_params()
        encrypted_password = ""
        if params["password"]:
            try:
                encrypted_password = encrypt_password(params["password"])
            except RuntimeError as exc:
                self.message_user(
                    request,
                    f"Не удалось применить тестовую БД: {exc}",
                    level=messages.ERROR,
                )
                return redirect(
                    "admin:analysis_app_portaldbconnectionsettings_change",
                    object_id,
                )

        obj.profile = PortalDbConnectionSettings.Profile.TEST
        obj.host = params["host"]
        obj.port = params["port"]
        obj.db_name = params["db_name"]
        obj.user = params["user"]
        if encrypted_password:
            obj.password_encrypted = encrypted_password
        obj.save()
        apply_portal_db_settings()
        self.message_user(request, "Применены параметры тестовой БД.", level=messages.SUCCESS)
        return redirect(
            "admin:analysis_app_portaldbconnectionsettings_change",
            object_id,
        )


@admin.register(CachedPU)
class CachedPUAdmin(admin.ModelAdmin):
    change_list_template = "admin/analysis_app/cachedpu_change_list.html"
    list_display = ("short_name", "full_name", "portal_pu_id", "updated_at")
    search_fields = ("short_name", "full_name", "portal_pu_id")
    ordering = ("short_name",)
    actions = ["recompute_pu_cache"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "recompute-cache/",
                self.admin_site.admin_view(self.recompute_cache_view),
                name="analysis_app_cachedpu_recompute_cache",
            )
        ]
        return custom_urls + urls

    def recompute_cache_view(self, request):
        call_command("sync_pu_cache", rebuild_embeddings=True)
        self.message_user(request, "PU cache recomputed.", messages.SUCCESS)
        return redirect("..")

    @admin.action(description="Recompute cache for selected PUs")
    def recompute_pu_cache(self, request, queryset):
        portal_ids = list(queryset.values_list("portal_pu_id", flat=True))
        gateway = get_portal_gateway()
        portal_pus = {
            pu.pu_id: PortalPURecord(
                pu_id=pu.pu_id,
                short_name=pu.short_name,
                full_name=pu.full_name,
            )
            for pu in gateway.list_pus()
            if pu.pu_id in portal_ids
        }
        updated = 0
        for portal_pu_id in portal_ids:
            portal_pu = portal_pus.get(portal_pu_id)
            if portal_pu is None:
                continue
            upsert_pu_cache(portal_pu, rebuild_embeddings=True)
            updated += 1
        self.message_user(
            request,
            f"Recomputed cache for {updated} PUs.",
            messages.SUCCESS,
        )


@admin.register(CachedSubdivision)
class CachedSubdivisionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "pu",
        "portal_subdivision_id",
        "embedding_present",
        "updated_at",
    )
    list_filter = ("pu",)
    search_fields = ("name", "portal_subdivision_id")
    actions = [rebuild_subdivision_embeddings]

    @admin.display(boolean=True)
    def embedding_present(self, obj):
        return bool(obj.embedding)


@admin.register(CachedSubdivisionAlias)
class CachedSubdivisionAliasAdmin(admin.ModelAdmin):
    list_display = ("alias_text", "subdivision", "updated_at")
    search_fields = ("alias_text", "normalized_alias")
    list_select_related = ("subdivision",)


@admin.register(SvodkaTemplate)
class SvodkaTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "scope",
        "pu_id",
        "pu_name",
        "is_active",
        "begin_marker",
        "end_marker",
        "updated_at",
    )
    list_filter = ("scope", "is_active")
    search_fields = ("pu_id", "pu_name")
    list_editable = ("is_active",)
