from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_auth", "0002_user_avatar_url_user_github_oauth_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="github_installation_account_login",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="github_oauth_username",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
