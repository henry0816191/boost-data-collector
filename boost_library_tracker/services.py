"""
Service layer for boost_library_tracker.
All creates/updates/deletes for this app's models must go through functions here.
See docs/Contributing.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    BoostDependency,
    BoostFile,
    BoostLibrary,
    BoostLibraryCategory,
    BoostLibraryCategoryRelationship,
    BoostLibraryRepository,
    BoostLibraryRoleRelationship,
    BoostLibraryVersion,
    BoostVersion,
    DependencyChangeLog,
)

if TYPE_CHECKING:
    from github_activity_tracker.models import GitHubFile, GitHubRepository
    from cppa_user_tracker.models import GitHubAccount


# --- BoostLibraryRepository ---
def get_or_create_boost_library_repo(
    github_repository: GitHubRepository,
) -> tuple[BoostLibraryRepository, bool]:
    """Get or create BoostLibraryRepository for a GitHub repository (inherited model).
    Creates only the child row (no parent save) to avoid NOT NULL errors on corrupt parent rows.
    """
    from django.utils import timezone

    existing = BoostLibraryRepository.objects.filter(
        githubrepository_ptr_id=github_repository.pk
    ).first()
    if existing is not None:
        existing.updated_at = timezone.now()
        existing.save(update_fields=["updated_at"])
        return existing, False
    from django.db import connection, IntegrityError

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO boost_library_tracker_boostlibraryrepository
                    (githubrepository_ptr_id, created_at, updated_at)
                VALUES (%s, %s, %s)
                """,
                [github_repository.pk, timezone.now(), timezone.now()],
            )
    except IntegrityError:
        existing = BoostLibraryRepository.objects.get(pk=github_repository.pk)
        return existing, False
    return BoostLibraryRepository.objects.get(pk=github_repository.pk), True


# --- BoostLibrary ---
def get_or_create_boost_library(
    repo: BoostLibraryRepository,
    name: str,
) -> tuple[BoostLibrary, bool]:
    """Get or create a BoostLibrary by repo and name. If exists, no extra fields to update."""
    if not (name and name.strip()):
        raise ValueError("Boost library name must not be empty.")
    return BoostLibrary.objects.get_or_create(
        repo=repo,
        name=name.strip(),
    )


# --- BoostFile ---
def get_or_create_boost_file(
    github_file: GitHubFile,
    library: BoostLibrary,
) -> tuple[BoostFile, bool]:
    """Get or create BoostFile linking a GitHubFile to a BoostLibrary. If exists, updates library."""
    obj, created = BoostFile.objects.get_or_create(
        github_file=github_file,
        defaults={"library": library},
    )
    if not created and obj.library_id != library.pk:
        obj.library = library
        obj.save(update_fields=["library_id"])
    return obj, created


# --- BoostVersion ---
def get_or_create_boost_version(
    version: str,
    version_created_at=None,
) -> tuple[BoostVersion, bool]:
    """Get or create BoostVersion by version string. If exists, updates version_created_at."""
    if not (version and version.strip()):
        raise ValueError("Boost version must not be empty.")
    obj, created = BoostVersion.objects.get_or_create(
        version=version.strip(),
        defaults={"version_created_at": version_created_at},
    )
    if (
        not created
        and version_created_at is not None
        and obj.version_created_at != version_created_at
    ):
        obj.version_created_at = version_created_at
        obj.save(update_fields=["version_created_at"])
    return obj, created


# --- BoostLibraryVersion ---
def get_or_create_boost_library_version(
    library: BoostLibrary,
    version: BoostVersion,
    cpp_version: str = "",
    description: str = "",
) -> tuple[BoostLibraryVersion, bool]:
    """Get or create BoostLibraryVersion for library + version. If exists, updates cpp_version and description."""
    obj, created = BoostLibraryVersion.objects.get_or_create(
        library=library,
        version=version,
        defaults={"cpp_version": cpp_version, "description": description},
    )
    if not created:
        obj.cpp_version = cpp_version
        obj.description = description
        obj.save(update_fields=["cpp_version", "description"])
    return obj, created


# --- BoostDependency ---
def add_boost_dependency(
    client_library: BoostLibrary,
    version: BoostVersion,
    dep_library: BoostLibrary,
) -> tuple[BoostDependency, bool]:
    """Add a dependency (idempotent). Returns (dependency, created)."""
    return BoostDependency.objects.get_or_create(
        client_library=client_library,
        version=version,
        dep_library=dep_library,
    )


# --- DependencyChangeLog ---
def add_dependency_changelog(
    client_library: BoostLibrary,
    dep_library: BoostLibrary,
    is_add: bool,
    created_at,
) -> tuple[DependencyChangeLog, bool]:
    """Add or update a dependency changelog entry. If exists (same client, dep, created_at), updates is_add. Returns (log, created)."""
    obj, created = DependencyChangeLog.objects.get_or_create(
        client_library=client_library,
        dep_library=dep_library,
        created_at=created_at,
        defaults={"is_add": is_add},
    )
    if not created and obj.is_add != is_add:
        obj.is_add = is_add
        obj.save(update_fields=["is_add"])
    return obj, created


# --- BoostLibraryCategory ---
def get_or_create_boost_library_category(
    name: str,
) -> tuple[BoostLibraryCategory, bool]:
    """Get or create BoostLibraryCategory by name."""
    if not (name and name.strip()):
        raise ValueError("Category name must not be empty.")
    return BoostLibraryCategory.objects.get_or_create(name=name.strip())


# --- BoostLibraryCategoryRelationship ---
def add_library_category(
    library: BoostLibrary,
    category: BoostLibraryCategory,
) -> tuple[BoostLibraryCategoryRelationship, bool]:
    """Link library to category (idempotent). Returns (relation, created)."""
    return BoostLibraryCategoryRelationship.objects.get_or_create(
        library=library,
        category=category,
    )


# --- BoostLibraryRoleRelationship ---
def add_library_version_role(
    library_version: BoostLibraryVersion,
    account: GitHubAccount,
    is_maintainer: bool = False,
    is_author: bool = False,
) -> tuple[BoostLibraryRoleRelationship, bool]:
    """Add or update maintainer/author for a library version. Returns (relation, created)."""
    rel, created = BoostLibraryRoleRelationship.objects.get_or_create(
        library_version=library_version,
        account=account,
        defaults={"is_maintainer": is_maintainer, "is_author": is_author},
    )
    if not created:
        rel.is_maintainer = rel.is_maintainer or is_maintainer
        rel.is_author = rel.is_author or is_author
        rel.save()
    return rel, created
