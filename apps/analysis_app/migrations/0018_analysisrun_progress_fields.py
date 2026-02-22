from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis_app", "0017_analysisrun_status_canceled"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysisrun",
            name="progress_done",
            field=models.PositiveIntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="analysisrun",
            name="progress_total",
            field=models.PositiveIntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="analysisrun",
            name="progress_updated_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
    ]
