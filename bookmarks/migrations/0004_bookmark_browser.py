from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bookmarks", "0003_bookmark_complete"),
    ]

    operations = [
        migrations.AddField(
            model_name="bookmark",
            name="browser",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
