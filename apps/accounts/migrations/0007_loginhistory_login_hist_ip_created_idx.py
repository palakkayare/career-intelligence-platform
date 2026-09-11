from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_encrypt_two_factor_secret"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="loginhistory",
            index=models.Index(
                fields=["ip_address", "-created_at"], name="login_hist_ip_created_idx"
            ),
        ),
    ]
