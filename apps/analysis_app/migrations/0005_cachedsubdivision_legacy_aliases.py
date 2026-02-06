from django.db import migrations

from apps.analysis_app.utils.subdivision_norm import normalize_text


def copy_legacy_aliases_to_rows(apps, schema_editor):
    CachedSubdivision = apps.get_model("analysis_app", "CachedSubdivision")
    CachedSubdivisionAlias = apps.get_model("analysis_app", "CachedSubdivisionAlias")

    for subdivision in CachedSubdivision.objects.all():
        legacy_aliases = subdivision.legacy_aliases or []
        if not isinstance(legacy_aliases, (list, tuple)):
            continue
        for alias_text in legacy_aliases:
            if not alias_text:
                continue
            normalized_alias = normalize_text(alias_text)
            if not normalized_alias:
                continue
            CachedSubdivisionAlias.objects.get_or_create(
                subdivision=subdivision,
                normalized_alias=normalized_alias,
                defaults={
                    "alias_text": alias_text,
                    "normalized_alias": normalized_alias,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("analysis_app", "0004_cachedsubdivisionalias"),
    ]

    operations = [
        migrations.RenameField(
            model_name="cachedsubdivision",
            old_name="aliases",
            new_name="legacy_aliases",
        ),
        migrations.RunPython(copy_legacy_aliases_to_rows, migrations.RunPython.noop),
    ]
