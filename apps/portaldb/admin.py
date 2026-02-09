from django import forms
from django.contrib import admin

from apps.classifier.models import EventType
from apps.portaldb.models import Event, Offender, Pu, Subdivision


class OffenderInline(admin.TabularInline):
    model = Offender
    extra = 1


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
class EventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "date_detection", "event_type", "article_of_law")
    search_fields = ("event_type", "article_of_law")
    list_filter = ("date_detection",)
    inlines = [OffenderInline]
    form = EventAdminForm


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
