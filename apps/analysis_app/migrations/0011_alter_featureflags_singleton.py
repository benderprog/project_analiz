from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis_app", "0010_featureflags_analysisrun_debug_pipeline"),
    ]

    operations = [
        migrations.RenameField(
            model_name="featureflags",
            old_name="singleton_id",
            new_name="id",
        ),
        migrations.AlterField(
            model_name="featureflags",
            name="debug_mode",
            field=models.BooleanField(default=False),
        ),
        migrations.RemoveField(
            model_name="featureflags",
            name="created_at",
        ),
    ]
