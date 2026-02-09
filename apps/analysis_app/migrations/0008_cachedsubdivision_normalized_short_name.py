from django.db import migrations, models

from apps.analysis_app.utils.text_normalize import normalize_subdivision_text


def backfill_normalized_name(apps, schema_editor) -> None:
    CachedSubdivision = apps.get_model("analysis_app", "CachedSubdivision")
    for subdivision in CachedSubdivision.objects.all():
        name = subdivision.name or ""
        normalized_name = normalize_subdivision_text(name)
        if normalized_name and normalized_name != subdivision.normalized_name:
            subdivision.normalized_name = normalized_name
            subdivision.save(update_fields=["normalized_name"])


class Migration(migrations.Migration):
    dependencies = [
        ("analysis_app", "0007_cachedpu_embeddings_split"),
    ]

    operations = [
        migrations.AddField(
            model_name="cachedsubdivision",
            name="normalized_short_name",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(backfill_normalized_name, migrations.RunPython.noop),
    ]
