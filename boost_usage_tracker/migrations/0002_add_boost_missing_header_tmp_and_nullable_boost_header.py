# Generated manually for Schema.md: BoostMissingHeaderTmp and nullable boost_header_id

from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("boost_usage_tracker", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="boostusage",
            name="boost_header",
            field=models.ForeignKey(
                blank=True,
                db_column="boost_header_id",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="external_usages",
                to="boost_library_tracker.boostfile",
            ),
        ),
        migrations.AddConstraint(
            model_name="boostusage",
            constraint=models.UniqueConstraint(
                condition=Q(boost_header__isnull=True),
                fields=("repo", "file_path"),
                name="boost_usage_tracker_usage_missing_header_uniq",
            ),
        ),
        migrations.CreateModel(
            name="BoostMissingHeaderTmp",
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
                ("header_name", models.CharField(db_index=True, max_length=512)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "usage",
                    models.ForeignKey(
                        db_column="usage_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="missing_header_tmp",
                        to="boost_usage_tracker.boostusage",
                    ),
                ),
            ],
            options={
                "verbose_name": "Boost Missing Header Tmp",
                "verbose_name_plural": "Boost Missing Header Tmp",
                "db_table": "boost_usage_tracker_boostmissingheadertmp",
                "ordering": ["usage", "header_name"],
            },
        ),
        migrations.AddConstraint(
            model_name="boostmissingheadertmp",
            constraint=models.UniqueConstraint(
                fields=("usage", "header_name"),
                name="boost_usage_tracker_missing_header_tmp_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="boostmissingheadertmp",
            index=models.Index(fields=["usage"], name="boost_missing_tmp_usage_id"),
        ),
    ]
