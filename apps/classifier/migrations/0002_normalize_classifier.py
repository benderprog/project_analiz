import uuid

from django.db import migrations, models


def migrate_classifier_data(apps, schema_editor):
    EventTypeClassifier = apps.get_model("classifier", "EventTypeClassifier")
    EventType = apps.get_model("classifier", "EventType")
    EventTypePattern = apps.get_model("classifier", "EventTypePattern")

    for row in EventTypeClassifier.objects.all():
        event_type_value = (row.event_type or "").strip()
        if not event_type_value:
            continue
        event_type_obj, _ = EventType.objects.get_or_create(event_type=event_type_value)
        pattern_value = (row.event_pattern or "").strip()
        if not pattern_value:
            continue
        EventTypePattern.objects.get_or_create(
            event_type=event_type_obj,
            pattern=pattern_value,
            defaults={"article_of_law": (row.article_of_law or "").strip() or None},
        )


class Migration(migrations.Migration):
    dependencies = [("classifier", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="EventType",
            fields=[
                (
                    "event_type_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("event_type", models.TextField(unique=True)),
            ],
            options={
                "verbose_name": "Event type",
                "verbose_name_plural": "Event types",
            },
        ),
        migrations.CreateModel(
            name="EventTypePattern",
            fields=[
                (
                    "event_type_pattern_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("pattern", models.TextField()),
                ("article_of_law", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "event_type",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="patterns",
                        to="classifier.eventtype",
                    ),
                ),
            ],
            options={
                "verbose_name": "Event type pattern",
                "verbose_name_plural": "Event type patterns",
            },
        ),
        migrations.AddConstraint(
            model_name="eventtypepattern",
            constraint=models.UniqueConstraint(
                fields=("event_type", "pattern"), name="unique_event_type_pattern"
            ),
        ),
        migrations.RunPython(migrate_classifier_data, migrations.RunPython.noop),
        migrations.DeleteModel(name="EventTypeClassifier"),
    ]
