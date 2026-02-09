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
    # Show short_name to match the subdivision primer and admin requirements.
    list_display = ("subdivision_id", "short_name", "name", "parent_pu")
    # Allow searching by short_name, full name, and parent PU naming.
    search_fields = ("short_name", "name", "parent_pu__short_name", "parent_pu__full_name")
    list_filter = ("parent_pu",)


@admin.register(Offender)
class OffenderAdmin(admin.ModelAdmin):
    list_display = ("offender_id", "second_name", "first_name", "date_of_birth", "event")
    search_fields = ("second_name", "first_name")
    list_filter = ("date_of_birth",)
