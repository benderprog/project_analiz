from django.contrib import admin

from apps.portaldb.models import Event, Offender, Pu, Subdivision


class OffenderInline(admin.TabularInline):
    model = Offender
    extra = 1


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "date_detection", "event_type", "article_of_law")
    search_fields = ("event_type", "article_of_law")
    list_filter = ("date_detection",)
    inlines = [OffenderInline]


@admin.register(Pu)
class PuAdmin(admin.ModelAdmin):
    list_display = ("pu_id", "short_name", "full_name")
    search_fields = ("short_name", "full_name")


@admin.register(Subdivision)
class SubdivisionAdmin(admin.ModelAdmin):
    list_display = ("subdivision_id", "name", "parent_pu")
    search_fields = ("name",)
    list_filter = ("parent_pu",)


@admin.register(Offender)
class OffenderAdmin(admin.ModelAdmin):
    list_display = ("offender_id", "second_name", "first_name", "date_of_birth", "event")
    search_fields = ("second_name", "first_name")
    list_filter = ("date_of_birth",)
