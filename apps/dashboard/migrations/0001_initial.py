import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("seekers", "0006_seekerskill_endorsement_count_skillendorsement"),
    ]

    operations = [
        migrations.CreateModel(
            name="SeekerDashboardState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "last_seen_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the seeker last left the dashboard. Drives the 'new since your last visit' items.",
                        null=True,
                    ),
                ),
                (
                    "seeker",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dashboard_state",
                        to="seekers.seekerprofile",
                    ),
                ),
            ],
            options={"db_table": "seeker_dashboard_state"},
        ),
    ]
