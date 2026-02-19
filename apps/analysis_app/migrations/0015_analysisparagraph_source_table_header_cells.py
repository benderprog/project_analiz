from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis_app", "0014_analysisparagraph_source_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysisparagraph",
            name="source_table_header_cells",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
