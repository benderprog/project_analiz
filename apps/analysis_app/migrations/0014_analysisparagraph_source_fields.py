from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis_app", "0013_analysisrun_pending_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysisparagraph",
            name="source_cells",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="analysisparagraph",
            name="source_kind",
            field=models.CharField(
                choices=[("paragraph", "Paragraph"), ("table_row", "Table row")],
                default="paragraph",
                max_length=20,
            ),
        ),
    ]
