from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis_app", "0016_svodkatemplate"),
    ]

    operations = [
        migrations.AlterField(
            model_name="analysisrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("created", "Created"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("done", "Done"),
                    ("failed", "Failed"),
                    ("canceled", "Canceled"),
                ],
                default="created",
                max_length=20,
            ),
        ),
    ]
