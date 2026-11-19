from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="useraccount",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
                help_text="Whether login must wait until the user sets a permanent password.",
            ),
        ),
    ]
