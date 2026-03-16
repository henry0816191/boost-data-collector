from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boost_library_docs_tracker", "0001_initial"),
    ]

    operations = [
        # Remove page_content from BoostDocContent
        migrations.RemoveField(
            model_name="boostdoccontent",
            name="page_content",
        ),
        # Drop old status index before removing the field
        migrations.RemoveIndex(
            model_name="boostlibrarydocumentation",
            name="boost_library_docs_tracker_lib_ver_status_ix",
        ),
        # Remove status field from BoostLibraryDocumentation
        migrations.RemoveField(
            model_name="boostlibrarydocumentation",
            name="status",
        ),
        # Add is_upserted to BoostLibraryDocumentation
        migrations.AddField(
            model_name="boostlibrarydocumentation",
            name="is_upserted",
            field=models.BooleanField(default=False, db_index=True),
        ),
        # Add new index on (boost_library_version, is_upserted)
        migrations.AddIndex(
            model_name="boostlibrarydocumentation",
            index=models.Index(
                fields=["boost_library_version", "is_upserted"],
                name="bl_docs_libver_upserted_ix",
            ),
        ),
    ]
