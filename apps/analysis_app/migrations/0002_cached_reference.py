import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("analysis_app", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CachedPU",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("portal_pu_id", models.UUIDField(unique=True)),
                ("short_name", models.CharField(max_length=255)),
                ("full_name", models.CharField(max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Cached PU",
                "verbose_name_plural": "Cached PUs",
            },
        ),
        migrations.CreateModel(
            name="CachedSubdivision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("portal_subdivision_id", models.UUIDField(unique=True)),
                ("name", models.CharField(max_length=255)),
                (
                    "pu",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="analysis_app.cachedpu"),
                ),
                ("normalized_name", models.TextField()),
                ("aliases", models.JSONField(blank=True, null=True)),
                ("embedding", models.JSONField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Cached Subdivision",
                "verbose_name_plural": "Cached Subdivisions",
            },
        ),
    ]
