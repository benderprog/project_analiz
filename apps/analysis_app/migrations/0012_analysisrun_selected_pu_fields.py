from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analysis_app", "0011_analysisrun_original_filename"),
    ]

    operations = [
        migrations.AlterField(
            model_name="analysisrun",
            name="selected_pu_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="analysisrun",
            name="selected_pu_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
