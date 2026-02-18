from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis_app", "0010_analysisrun_async_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysisrun",
            name="original_filename",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
