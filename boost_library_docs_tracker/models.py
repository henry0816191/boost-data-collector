"""
Models per docs/Schema.md section 10: Boost Library Docs Tracker.
References boost_library_tracker.BoostLibraryVersion and BoostVersion (cross-app FK, read-only from here).
"""

from django.db import models


class BoostDocContent(models.Model):
    """
    One row per unique document content, keyed by content_hash (not URL).

    Our aim is to avoid repeating the same content: the unique key is content_hash
    (SHA-256 of the page text). The same URL may produce a new row if the content
    changes; identical content at different URLs or versions shares one row.
    url is stored for reference and workspace lookup but is not the uniqueness
    constraint. Page content is NOT stored in the DB; it lives in the workspace files.

    first_version / last_version track the earliest and latest Boost version in
    which this content was observed. is_upserted tracks whether it has been
    successfully upserted to Pinecone.
    """

    url = models.TextField(db_index=True)
    content_hash = models.CharField(max_length=64, unique=True, db_index=True)
    first_version = models.ForeignKey(
        "boost_library_tracker.BoostVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="first_doc_contents",
        db_column="first_version_id",
    )
    last_version = models.ForeignKey(
        "boost_library_tracker.BoostVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="last_doc_contents",
        db_column="last_version_id",
    )
    is_upserted = models.BooleanField(default=False)
    scraped_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "boost_library_docs_tracker_boostdoccontent"
        ordering = ["url"]

    def __str__(self):
        return self.url


class BoostLibraryDocumentation(models.Model):
    """
    Join table between BoostLibraryVersion and BoostDocContent.
    One row per (library-version, page) pair — records which pages were found
    under a given (library, version) combination.
    """

    boost_library_version = models.ForeignKey(
        "boost_library_tracker.BoostLibraryVersion",
        on_delete=models.CASCADE,
        related_name="doc_relations",
        db_column="boost_library_version_id",
    )
    boost_doc_content = models.ForeignKey(
        BoostDocContent,
        on_delete=models.CASCADE,
        related_name="library_relations",
        db_column="boost_doc_content_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "boost_library_docs_tracker_boostlibrarydocumentation"
        ordering = ["boost_library_version", "boost_doc_content"]
        constraints = [
            models.UniqueConstraint(
                fields=["boost_library_version", "boost_doc_content"],
                name="boost_library_docs_tracker_lib_ver_content_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["boost_library_version"],
                name="bl_docs_libver_ix",
            )
        ]

    def __str__(self):
        return (
            f"BoostLibraryDocumentation("
            f"library_version={self.boost_library_version_id}, "
            f"content={self.boost_doc_content_id})"
        )
