from django.contrib import admin, messages
from django.core.management import call_command
from django.shortcuts import redirect
from django.urls import path

from apps.analysis_app.models import CachedPU, CachedSubdivision, CachedSubdivisionAlias
from apps.analysis_app.pu_cache import upsert_pu_cache
from apps.analysis_app.portal_records import PortalPURecord
from apps.portaldb.gateway import get_portal_gateway


@admin.action(description="Rebuild embeddings")
def rebuild_subdivision_embeddings(modeladmin, request, queryset):
    call_command("sync_portal_reference", rebuild_embeddings=True)


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
