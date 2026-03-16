import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boost_library_docs_tracker", "0002_remove_page_content_and_status_add_is_upserted"),
        ("boost_library_tracker", "0001_initial"),
    ]

    operations = [
        # BoostDocContent: make url non-unique (content_hash becomes the unique key)
        migrations.AlterField(
            model_name="boostdoccontent",
            name="url",
            field=models.TextField(db_index=True),
        ),
        # BoostDocContent: make content_hash unique
        migrations.AlterField(
            model_name="boostdoccontent",
            name="content_hash",
            field=models.CharField(max_length=64, unique=True, db_index=True),
        ),
        # BoostDocContent: add first_version FK
        migrations.AddField(
            model_name="boostdoccontent",
            name="first_version",
            field=models.ForeignKey(
                blank=True,
                db_column="first_version_id",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="first_doc_contents",
                to="boost_library_tracker.boostversion",
            ),
        ),
        # BoostDocContent: add last_version FK
        migrations.AddField(
            model_name="boostdoccontent",
            name="last_version",
            field=models.ForeignKey(
                blank=True,
                db_column="last_version_id",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="last_doc_contents",
                to="boost_library_tracker.boostversion",
            ),
        ),
        # BoostDocContent: move is_upserted here (from BoostLibraryDocumentation)
        migrations.AddField(
            model_name="boostdoccontent",
            name="is_upserted",
            field=models.BooleanField(default=False),
        ),
        # BoostLibraryDocumentation: remove is_upserted (now on BoostDocContent)
        migrations.RemoveIndex(
            model_name="boostlibrarydocumentation",
            name="bl_docs_libver_upserted_ix",
        ),
        migrations.RemoveField(
            model_name="boostlibrarydocumentation",
            name="is_upserted",
        ),
        # BoostLibraryDocumentation: remove page_count and updated_at
        migrations.RemoveField(
            model_name="boostlibrarydocumentation",
            name="page_count",
        ),
        migrations.RemoveField(
            model_name="boostlibrarydocumentation",
            name="updated_at",
        ),
        # BoostLibraryDocumentation: add simple index on boost_library_version
        migrations.AddIndex(
            model_name="boostlibrarydocumentation",
            index=models.Index(
                fields=["boost_library_version"],
                name="bl_docs_libver_ix",
            ),
        ),
    ]
