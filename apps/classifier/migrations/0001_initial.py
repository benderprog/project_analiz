import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="EventTypeClassifier",
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
                ("event_type", models.TextField()),
                ("event_pattern", models.TextField()),
                ("article_of_law", models.CharField(max_length=255)),
            ],
            options={
                "verbose_name": "Event type classifier",
                "verbose_name_plural": "Event type classifiers",
            },
        ),
    ]
