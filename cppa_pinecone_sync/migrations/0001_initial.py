"""
Initial migration for cppa_pinecone_sync: PineconeFailList and PineconeSyncStatus.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PineconeFailList",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("failed_id", models.CharField(db_index=True, max_length=255)),
                ("app_id", models.IntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "cppa_pinecone_sync_pineconefaillist",
                "ordering": ["id"],
                "verbose_name": "Pinecone fail list entry",
                "verbose_name_plural": "Pinecone fail list entries",
            },
        ),
        migrations.CreateModel(
            name="PineconeSyncStatus",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "app_id",
                    models.IntegerField(db_index=True, unique=True),
                ),
                (
                    "final_sync_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "cppa_pinecone_sync_pineconesyncstatus",
                "ordering": ["app_id"],
                "verbose_name": "Pinecone sync status",
                "verbose_name_plural": "Pinecone sync statuses",
            },
        ),
    ]
