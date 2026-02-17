from django import forms
from django.contrib import admin

from apps.classifier.models import EventType
from apps.analysis_app.portal_db_runtime import (
    apply_portal_db_settings,
    get_portal_settings_singleton,
)
from apps.portaldb.models import Event, Offender, Pu, Subdivision


class PortalDbAccessModeMixin:
    def _is_prod_read_only(self):
        settings_obj = get_portal_settings_singleton()
        if not settings_obj:
            return False
        return settings_obj.profile == settings_obj.Profile.PROD

    def has_add_permission(self, request):
        if self._is_prod_read_only():
            return False
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if self._is_prod_read_only():
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._is_prod_read_only():
            return False
        return super().has_delete_permission(request, obj)


class OffenderInline(admin.TabularInline):
    model = Offender
    fields = ("second_name", "first_name", "patronymic_name", "date_of_birth")
    extra = 0
    show_change_link = True

    def _is_prod_read_only(self):
        settings_obj = get_portal_settings_singleton()
        return bool(settings_obj and settings_obj.profile == "PROD")

    def has_add_permission(self, request, obj=None):
        if self._is_prod_read_only():
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if self._is_prod_read_only():
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._is_prod_read_only():
            return False
        return super().has_delete_permission(request, obj)


class EventAdminForm(forms.ModelForm):
    event_type = forms.ChoiceField()

    class Meta:
        model = Event
        fields = "__all__"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        event_types = list(
            EventType.objects.order_by("event_type").values_list("event_type", flat=True)
        )
        seen = set()
        unique_event_types = []
        for event_type in event_types:
            if not event_type or event_type in seen:
                continue
            unique_event_types.append(event_type)
            seen.add(event_type)

        choices = [("", "---------")] + [
            (event_type, event_type) for event_type in unique_event_types
        ]

        instance_event_type = getattr(self.instance, "event_type", "")
        if instance_event_type and instance_event_type not in seen:
            choices.append((instance_event_type, instance_event_type))

        self.fields["event_type"].choices = choices


@admin.register(Event)
class EventAdmin(PortalDbAccessModeMixin, admin.ModelAdmin):
    list_display = ("event_id", "date_detection", "event_type", "article_of_law")
    search_fields = ("event_type", "article_of_law")
    list_filter = ("date_detection",)
    inlines = [OffenderInline]
    form = EventAdminForm

    def get_queryset(self, request):
        apply_portal_db_settings()
        return super().get_queryset(request)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "find_subdivision_unit" and formfield is not None:
            # Keep the human-readable label (full name + PU) even if __str__ changes later.
            formfield.label_from_instance = (
                lambda obj: obj.display_label() if hasattr(obj, "display_label") else str(obj)
            )
        return formfield


@admin.register(Pu)
class PuAdmin(PortalDbAccessModeMixin, admin.ModelAdmin):
    list_display = ("pu_id", "short_name", "full_name")
    search_fields = ("short_name", "full_name")

    def get_queryset(self, request):
        apply_portal_db_settings()
        return super().get_queryset(request)


@admin.register(Subdivision)
class SubdivisionAdmin(PortalDbAccessModeMixin, admin.ModelAdmin):
    # Show short_name to match the subdivision primer and admin requirements.
    list_display = ("subdivision_id", "short_name", "name", "parent_pu")
    # Allow searching by short_name, full name, and parent PU naming.
    search_fields = ("short_name", "name", "parent_pu__short_name", "parent_pu__full_name")
    list_filter = ("parent_pu",)

    def get_queryset(self, request):
        apply_portal_db_settings()
        return super().get_queryset(request)


@admin.register(Offender)
class OffenderAdmin(PortalDbAccessModeMixin, admin.ModelAdmin):
    list_display = (
        "second_name",
        "first_name",
        "patronymic_name",
        "date_of_birth",
        "event",
    )
    ordering = ("second_name", "first_name", "patronymic_name")
    search_fields = ("second_name", "first_name", "patronymic_name")
    list_filter = ("date_of_birth",)
    fields = ("second_name", "first_name", "patronymic_name", "date_of_birth", "event")

    def get_queryset(self, request):
        apply_portal_db_settings()
        return super().get_queryset(request)
