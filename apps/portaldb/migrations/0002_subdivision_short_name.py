from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portaldb", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="subdivision",
                    name="short_name",
                    field=models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        max_length=255,
                    ),
                )
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE subdivision ADD COLUMN IF NOT EXISTS short_name varchar(255);",
                    reverse_sql=migrations.RunSQL.noop,
                )
            ],
        )
    ]
