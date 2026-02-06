from django.contrib import admin
from django.core.management import call_command

from apps.analysis_app.models import CachedPU, CachedSubdivision


@admin.action(description="Rebuild embeddings")
def rebuild_subdivision_embeddings(modeladmin, request, queryset):
    call_command("sync_portal_reference", rebuild_embeddings=True)


@admin.register(CachedPU)
class CachedPUAdmin(admin.ModelAdmin):
    list_display = ("short_name", "full_name", "portal_pu_id", "updated_at")
    search_fields = ("short_name", "full_name", "portal_pu_id")
    ordering = ("short_name",)


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
