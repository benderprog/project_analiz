from django import forms
from django.test import TestCase

from apps.classifier.models import EventType
from apps.portaldb.admin import EventAdminForm
from apps.portaldb.models import Event


class EventAdminFormEventTypeTests(TestCase):
    def test_event_type_field_uses_classifier_values(self):
        EventType.objects.create(event_type="Fire")
        EventType.objects.create(event_type="Robbery")

        form = EventAdminForm()

        self.assertIsInstance(form.fields["event_type"], forms.ChoiceField)
        choices = [choice[0] for choice in form.fields["event_type"].choices]

        self.assertIn("Fire", choices)
        self.assertIn("Robbery", choices)

    def test_event_type_includes_unknown_instance_value(self):
        EventType.objects.create(event_type="Theft")
        instance = Event(event_type="UNKNOWN_TYPE")

        form = EventAdminForm(instance=instance)

        choices = [choice[0] for choice in form.fields["event_type"].choices]

        self.assertIn("UNKNOWN_TYPE", choices)
