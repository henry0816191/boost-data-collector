import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("boost_library_tracker", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="BoostDocContent",
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
                ("url", models.TextField(db_index=True, unique=True)),
                ("content_hash", models.CharField(db_index=True, max_length=64)),
                ("page_content", models.TextField()),
                ("scraped_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "boost_library_docs_tracker_boostdoccontent",
                "ordering": ["url"],
            },
        ),
        migrations.CreateModel(
            name="BoostLibraryDocumentation",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("synced", "Synced"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("page_count", models.IntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "boost_doc_content",
                    models.ForeignKey(
                        db_column="boost_doc_content_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="library_relations",
                        to="boost_library_docs_tracker.boostdoccontent",
                    ),
                ),
                (
                    "boost_library_version",
                    models.ForeignKey(
                        db_column="boost_library_version_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="doc_relations",
                        to="boost_library_tracker.boostlibraryversion",
                    ),
                ),
            ],
            options={
                "db_table": "boost_library_docs_tracker_boostlibrarydocumentation",
                "ordering": ["boost_library_version", "boost_doc_content"],
            },
        ),
        migrations.AddConstraint(
            model_name="boostlibrarydocumentation",
            constraint=models.UniqueConstraint(
                fields=["boost_library_version", "boost_doc_content"],
                name="boost_library_docs_tracker_lib_ver_content_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="boostlibrarydocumentation",
            index=models.Index(
                fields=["boost_library_version", "status"],
                name="boost_library_docs_tracker_lib_ver_status_ix",
            ),
        ),
    ]
