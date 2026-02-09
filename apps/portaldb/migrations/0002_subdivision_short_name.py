from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portaldb", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="subdivision",
            name="short_name",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
    ]
