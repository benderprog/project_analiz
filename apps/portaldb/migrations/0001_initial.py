import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Pu",
            fields=[
                (
                    "pu_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("full_name", models.CharField(max_length=255)),
                ("short_name", models.CharField(max_length=255)),
            ],
            options={
                "db_table": "pu",
                "verbose_name": "PU",
                "verbose_name_plural": "PUs",
            },
        ),
        migrations.CreateModel(
            name="Subdivision",
            fields=[
                (
                    "subdivision_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "parent_pu",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="portaldb.pu"
                    ),
                ),
            ],
            options={
                "db_table": "subdivision",
                "verbose_name": "Subdivision",
                "verbose_name_plural": "Subdivisions",
            },
        ),
        migrations.CreateModel(
            name="Event",
            fields=[
                (
                    "event_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("date_detection", models.DateTimeField()),
                ("event_type", models.TextField()),
                ("article_of_law", models.CharField(max_length=255)),
                (
                    "find_subdivision_unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="portaldb.subdivision",
                    ),
                ),
            ],
            options={
                "db_table": "event",
                "verbose_name": "Event",
                "verbose_name_plural": "Events",
            },
        ),
        migrations.CreateModel(
            name="Offender",
            fields=[
                (
                    "offender_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("first_name", models.CharField(max_length=255)),
                ("second_name", models.CharField(max_length=255)),
                ("patronymic_name", models.CharField(blank=True, max_length=255)),
                ("date_of_birth", models.DateField()),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="offenders",
                        to="portaldb.event",
                    ),
                ),
            ],
            options={
                "db_table": "offenders",
                "verbose_name": "Offender",
                "verbose_name_plural": "Offenders",
            },
        ),
    ]
