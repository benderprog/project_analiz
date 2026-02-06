from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analysis_app", "0002_cached_reference"),
    ]

    operations = [
        migrations.AddField(
            model_name="cachedsubdivision",
            name="embedding_source_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="cachedsubdivision",
            name="embedding_updated_at",
            field=models.DateTimeField(null=True),
        ),
    ]
