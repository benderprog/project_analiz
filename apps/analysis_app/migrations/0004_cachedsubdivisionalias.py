from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("analysis_app", "0003_cachedsubdivision_embedding_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="CachedSubdivisionAlias",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("alias_text", models.TextField()),
                ("normalized_alias", models.TextField(db_index=True)),
                ("embedding", models.JSONField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "subdivision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="aliases",
                        to="analysis_app.cachedsubdivision",
                    ),
                ),
            ],
            options={
                "verbose_name": "Cached Subdivision Alias",
                "verbose_name_plural": "Cached Subdivision Aliases",
            },
        ),
        migrations.AddConstraint(
            model_name="cachedsubdivisionalias",
            constraint=models.UniqueConstraint(
                fields=("subdivision", "normalized_alias"),
                name="uniq_cached_subdivision_alias",
            ),
        ),
    ]
