from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis_app", "0012_analysisrun_selected_pu_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysisrun",
            name="created_session_key",
            field=models.CharField(blank=True, db_index=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="analysisrun",
            name="detected_pu_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="analysisrun",
            name="detected_pu_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
