from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("classifier", "0002_normalize_classifier")]

    operations = [
        migrations.AddField(
            model_name="eventtype",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="eventtypepattern",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
