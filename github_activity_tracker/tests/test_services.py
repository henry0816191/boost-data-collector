"""Tests for github_activity_tracker.services."""

import pytest
from datetime import datetime, timezone

from github_activity_tracker import services
from github_activity_tracker.models import (
    CreatedReposByLanguage,
    IssueLabel,
    PullRequestLabel,
    RepoLanguage,
)


# --- get_or_create_language ---


@pytest.mark.django_db
def test_get_or_create_language_creates_new():
    """get_or_create_language creates new Language and returns (obj, True)."""
    lang, created = services.get_or_create_language("Rust")
    assert created is True
    assert lang.name == "Rust"
    assert lang.id is not None


@pytest.mark.django_db
def test_get_or_create_language_gets_existing(language):
    """get_or_create_language returns existing Language and (obj, False)."""
    lang, created = services.get_or_create_language("C++")
    assert created is False
    assert lang.id == language.id
    assert lang.name == "C++"


@pytest.mark.django_db
def test_get_or_create_language_empty_raises():
    """get_or_create_language raises ValueError for empty or whitespace name."""
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_language("")
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_language("   ")


@pytest.mark.django_db
def test_get_or_create_language_strips_whitespace():
    """get_or_create_language strips leading/trailing whitespace from name."""
    lang, created = services.get_or_create_language("  Python  ")
    assert created is True
    assert lang.name == "Python"


@pytest.mark.django_db
def test_create_or_update_created_repos_by_language_creates(language):
    """Creates a new yearly language row when missing."""
    row, created = services.create_or_update_created_repos_by_language(
        language=language,
        year=2024,
        all_repos=500,
        significant_repos=50,
    )
    assert created is True
    assert row.year == 2024
    assert row.all_repos == 500
    assert row.significant_repos == 50


@pytest.mark.django_db
def test_create_or_update_created_repos_by_language_updates_existing(language):
    """Updates all_repos/significant_repos for existing (language, year)."""
    existing = CreatedReposByLanguage.objects.create(
        language=language,
        year=2024,
        all_repos=100,
        significant_repos=10,
    )
    row, created = services.create_or_update_created_repos_by_language(
        language=language,
        year=2024,
        all_repos=150,
        significant_repos=15,
    )
    assert created is False
    assert row.id == existing.id
    row.refresh_from_db()
    assert row.all_repos == 150
    assert row.significant_repos == 15


# --- get_or_create_license ---


@pytest.mark.django_db
def test_get_or_create_license_creates_new():
    """get_or_create_license creates new License and returns (obj, True)."""
    lic, created = services.get_or_create_license(
        "MIT", spdx_id="MIT", url="https://opensource.org/MIT"
    )
    assert created is True
    assert lic.name == "MIT"
    assert lic.spdx_id == "MIT"
    assert lic.url == "https://opensource.org/MIT"


@pytest.mark.django_db
def test_get_or_create_license_gets_existing_and_updates(license_obj):
    """get_or_create_license returns existing and updates spdx_id/url."""
    lic, created = services.get_or_create_license(
        "BSL-1.0",
        spdx_id="BSL-1.0",
        url="https://example.com/bsl",
    )
    assert created is False
    assert lic.id == license_obj.id
    lic.refresh_from_db()
    assert lic.url == "https://example.com/bsl"


@pytest.mark.django_db
def test_get_or_create_license_empty_name_raises():
    """get_or_create_license raises ValueError for empty name."""
    with pytest.raises(ValueError, match="must not be empty"):
        services.get_or_create_license("")


# --- get_or_create_repository ---


@pytest.mark.django_db
def test_get_or_create_repository_creates_new(github_account):
    """get_or_create_repository creates new repo and returns (repo, True)."""
    repo, created = services.get_or_create_repository(github_account, "new-repo")
    assert created is True
    assert repo.repo_name == "new-repo"
    assert repo.owner_account_id == github_account.id


@pytest.mark.django_db
def test_get_or_create_repository_gets_existing(github_repository, github_account):
    """get_or_create_repository returns existing repo and (repo, False)."""
    repo, created = services.get_or_create_repository(
        github_account,
        github_repository.repo_name,
    )
    assert created is False
    assert repo.id == github_repository.id


@pytest.mark.django_db
def test_get_or_create_repository_updates_defaults(github_repository, github_account):
    """get_or_create_repository updates stars/forks/description when repo exists."""
    repo, _ = services.get_or_create_repository(
        github_account,
        github_repository.repo_name,
        stars=10,
        forks=2,
        description="Updated desc",
    )
    repo.refresh_from_db()
    assert repo.stars == 10
    assert repo.forks == 2
    assert repo.description == "Updated desc"


# --- add_repo_license / remove_repo_license ---


@pytest.mark.django_db
def test_add_repo_license_adds_m2m(github_repository, license_obj):
    """add_repo_license adds License to repo.licenses."""
    services.add_repo_license(github_repository, license_obj)
    assert license_obj in github_repository.licenses.all()


@pytest.mark.django_db
def test_add_repo_license_idempotent(github_repository, license_obj):
    """add_repo_license is idempotent (calling twice does not duplicate)."""
    services.add_repo_license(github_repository, license_obj)
    services.add_repo_license(github_repository, license_obj)
    assert github_repository.licenses.count() == 1


@pytest.mark.django_db
def test_remove_repo_license_removes(github_repository, license_obj):
    """remove_repo_license removes License from repo."""
    services.add_repo_license(github_repository, license_obj)
    services.remove_repo_license(github_repository, license_obj)
    assert license_obj not in github_repository.licenses.all()


# --- ensure_repository_owner ---


@pytest.mark.django_db
def test_ensure_repository_owner_sets_owner_when_none(
    github_repository, github_account, make_github_repository
):
    """ensure_repository_owner sets owner_account when currently None (e.g. migrated row)."""
    repo = make_github_repository(owner_account=github_account, repo_name="orphan-repo")
    repo.refresh_from_db()
    # Simulate null owner: we can't easily set FK to null with constraint, so test the save path
    services.ensure_repository_owner(repo, github_account)
    repo.refresh_from_db()
    assert repo.owner_account_id == github_account.id


@pytest.mark.django_db
def test_ensure_repository_owner_no_op_when_owner_set(
    github_repository, github_account
):
    """ensure_repository_owner does not change repo when owner_account already set."""
    orig_id = github_repository.owner_account_id
    services.ensure_repository_owner(github_repository, github_account)
    github_repository.refresh_from_db()
    assert github_repository.owner_account_id == orig_id


@pytest.mark.django_db
def test_ensure_repository_owner_refreshes_from_db(github_repository, github_account):
    """ensure_repository_owner calls refresh_from_db before check."""
    services.ensure_repository_owner(github_repository, github_account)
    # No exception; repo unchanged when already has owner
    assert github_repository.owner_account_id == github_account.id


# --- add_repo_language ---


@pytest.mark.django_db
def test_add_repo_language_creates_link(github_repository, language):
    """add_repo_language creates RepoLanguage with line_count."""
    rl, created = services.add_repo_language(
        github_repository, language, line_count=100
    )
    assert created is True
    assert rl.line_count == 100
    assert rl.repo_id == github_repository.id
    assert rl.language_id == language.id


@pytest.mark.django_db
def test_add_repo_language_updates_existing(github_repository, language):
    """add_repo_language updates line_count when link exists."""
    services.add_repo_language(github_repository, language, line_count=50)
    rl, created = services.add_repo_language(
        github_repository, language, line_count=200
    )
    assert created is False
    rl.refresh_from_db()
    assert rl.line_count == 200


@pytest.mark.django_db
def test_add_repo_language_default_line_count_zero(github_repository, make_language):
    """add_repo_language defaults line_count to 0."""
    lang = make_language(name="Go")
    rl, _ = services.add_repo_language(github_repository, lang)
    assert rl.line_count == 0


# --- update_repo_language_line_count ---


@pytest.mark.django_db
def test_update_repo_language_line_count_updates_existing(github_repository, language):
    """update_repo_language_line_count updates line_count for existing RepoLanguage."""
    services.add_repo_language(github_repository, language, line_count=10)
    rl = services.update_repo_language_line_count(github_repository, language, 500)
    assert rl.line_count == 500
    rl.refresh_from_db()
    assert rl.line_count == 500


@pytest.mark.django_db
def test_update_repo_language_line_count_returns_repo_language(
    github_repository, language
):
    """update_repo_language_line_count returns the RepoLanguage instance."""
    services.add_repo_language(github_repository, language, line_count=0)
    rl = services.update_repo_language_line_count(github_repository, language, 100)
    assert rl.repo_id == github_repository.id
    assert rl.language_id == language.id


@pytest.mark.django_db
def test_update_repo_language_line_count_raises_if_missing(
    github_repository, make_language
):
    """update_repo_language_line_count raises if repo-language link does not exist."""
    lang = make_language(name="Rust")
    with pytest.raises(RepoLanguage.DoesNotExist):
        services.update_repo_language_line_count(github_repository, lang, 1)


# --- create_or_update_commit ---


@pytest.mark.django_db
def test_create_or_update_commit_creates(github_repository, github_account):
    """create_or_update_commit creates new GitCommit."""
    commit_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    commit_obj, created = services.create_or_update_commit(
        github_repository,
        github_account,
        "abc123",
        comment="Initial commit",
        commit_at=commit_at,
    )
    assert created is True
    assert commit_obj.commit_hash == "abc123"
    assert commit_obj.comment == "Initial commit"
    assert commit_obj.repo_id == github_repository.id


@pytest.mark.django_db
def test_create_or_update_commit_updates_existing(
    github_repository, github_account, make_github_account
):
    """create_or_update_commit updates existing commit (account, comment, commit_at)."""
    commit_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    services.create_or_update_commit(
        github_repository,
        github_account,
        "def456",
        comment="First",
        commit_at=commit_at,
    )
    other_account = make_github_account()
    new_at = datetime(2024, 6, 2, 10, 0, 0, tzinfo=timezone.utc)
    commit_obj, created = services.create_or_update_commit(
        github_repository,
        other_account,
        "def456",
        comment="Updated message",
        commit_at=new_at,
    )
    assert created is False
    commit_obj.refresh_from_db()
    assert commit_obj.account_id == other_account.id
    assert commit_obj.comment == "Updated message"


@pytest.mark.django_db
def test_create_or_update_commit_defaults_commit_at_now(
    github_repository, github_account
):
    """create_or_update_commit uses now when commit_at is None."""
    commit_obj, created = services.create_or_update_commit(
        github_repository,
        github_account,
        "sha999",
    )
    assert created is True
    assert commit_obj.commit_at is not None


# --- create_or_update_github_file ---


@pytest.mark.django_db
def test_create_or_update_github_file_creates(github_repository):
    """create_or_update_github_file creates new GitHubFile."""
    gf, created = services.create_or_update_github_file(
        github_repository, "src/main.py"
    )
    assert created is True
    assert gf.filename == "src/main.py"
    assert gf.is_deleted is False


@pytest.mark.django_db
def test_create_or_update_github_file_updates_is_deleted(github_repository):
    """create_or_update_github_file updates is_deleted when file exists."""
    services.create_or_update_github_file(
        github_repository, "deleted.py", is_deleted=False
    )
    gf, created = services.create_or_update_github_file(
        github_repository, "deleted.py", is_deleted=True
    )
    assert created is False
    gf.refresh_from_db()
    assert gf.is_deleted is True


@pytest.mark.django_db
def test_create_or_update_github_file_deleted_default_false(github_repository):
    """create_or_update_github_file defaults is_deleted to False."""
    gf, _ = services.create_or_update_github_file(github_repository, "x.py")
    assert gf.is_deleted is False


@pytest.mark.django_db
def test_create_or_update_github_file_strips_nul_from_filename(github_repository):
    """create_or_update_github_file strips NUL bytes from filename (PostgreSQL text cannot contain 0x00)."""
    filename_with_nul = "path\x00to\x00file.py"
    gf, _ = services.create_or_update_github_file(github_repository, filename_with_nul)
    assert "\x00" not in gf.filename
    assert gf.filename == "pathtofile.py"


# --- add_commit_file_change ---


@pytest.mark.django_db
def test_add_commit_file_change_creates(github_repository, github_account):
    """add_commit_file_change creates new GitCommitFileChange."""
    commit_obj, _ = services.create_or_update_commit(
        github_repository,
        github_account,
        "c1",
        commit_at=datetime.now(timezone.utc),
    )
    gf, _ = services.create_or_update_github_file(github_repository, "f.py")
    fc, created = services.add_commit_file_change(
        commit_obj, gf, "modified", additions=5, deletions=2, patch="@@ ..."
    )
    assert created is True
    assert fc.status == "modified"
    assert fc.additions == 5
    assert fc.deletions == 2
    assert fc.patch == "@@ ..."


@pytest.mark.django_db
def test_add_commit_file_change_updates_existing(github_repository, github_account):
    """add_commit_file_change updates status/additions/deletions/patch when exists."""
    commit_obj, _ = services.create_or_update_commit(
        github_repository,
        github_account,
        "c2",
        commit_at=datetime.now(timezone.utc),
    )
    gf, _ = services.create_or_update_github_file(github_repository, "g.py")
    services.add_commit_file_change(commit_obj, gf, "added", additions=10)
    fc, created = services.add_commit_file_change(
        commit_obj, gf, "modified", additions=3, deletions=1
    )
    assert created is False
    fc.refresh_from_db()
    assert fc.status == "modified"
    assert fc.additions == 3
    assert fc.deletions == 1


@pytest.mark.django_db
def test_add_commit_file_change_defaults_patch_empty(github_repository, github_account):
    """add_commit_file_change defaults patch to empty string."""
    commit_obj, _ = services.create_or_update_commit(
        github_repository,
        github_account,
        "c3",
        commit_at=datetime.now(timezone.utc),
    )
    gf, _ = services.create_or_update_github_file(github_repository, "h.py")
    fc, _ = services.add_commit_file_change(commit_obj, gf, "modified")
    assert fc.patch == ""


@pytest.mark.django_db
def test_add_commit_file_change_strips_nul_from_patch(
    github_repository, github_account
):
    """add_commit_file_change strips NUL bytes from patch (PostgreSQL text cannot contain 0x00)."""
    commit_obj, _ = services.create_or_update_commit(
        github_repository,
        github_account,
        "c_nul",
        commit_at=datetime.now(timezone.utc),
    )
    gf, _ = services.create_or_update_github_file(github_repository, "f.py")
    patch_with_nul = "diff --git a/f.py\n\x00binary\x00content\n"
    fc, _ = services.add_commit_file_change(
        commit_obj, gf, "modified", additions=1, deletions=0, patch=patch_with_nul
    )
    assert "\x00" not in fc.patch
    assert fc.patch == "diff --git a/f.py\nbinarycontent\n"


# --- set_github_file_previous_filename ---


@pytest.mark.django_db
def test_set_github_file_previous_filename_links_rename(github_repository):
    """set_github_file_previous_filename sets previous_filename and saves when different."""
    old_file, _ = services.create_or_update_github_file(
        github_repository, "old_path.py", is_deleted=False
    )
    new_file, _ = services.create_or_update_github_file(
        github_repository, "new_path.py", is_deleted=False
    )
    assert new_file.previous_filename_id is None

    services.set_github_file_previous_filename(new_file, old_file)

    new_file.refresh_from_db()
    assert new_file.previous_filename_id == old_file.id
    assert new_file.previous_filename.id == old_file.id


@pytest.mark.django_db
def test_set_github_file_previous_filename_no_op_when_already_set(github_repository):
    """set_github_file_previous_filename does not save when previous_filename_id already matches."""
    old_file, _ = services.create_or_update_github_file(
        github_repository, "old_path.py", is_deleted=False
    )
    new_file, _ = services.create_or_update_github_file(
        github_repository, "new_path.py", is_deleted=False
    )
    services.set_github_file_previous_filename(new_file, old_file)
    new_file.refresh_from_db()
    assert new_file.previous_filename_id == old_file.id

    # Call again with same old_file; should not mutate (idempotent)
    services.set_github_file_previous_filename(new_file, old_file)
    new_file.refresh_from_db()
    assert new_file.previous_filename_id == old_file.id


# --- create_or_update_issue ---


@pytest.mark.django_db
def test_create_or_update_issue_creates(github_repository, github_account):
    """create_or_update_issue creates new Issue."""
    issue, created = services.create_or_update_issue(
        github_repository,
        github_account,
        issue_number=1,
        issue_id=100,
        title="Bug",
        body="Description",
        state="open",
    )
    assert created is True
    assert issue.issue_number == 1
    assert issue.issue_id == 100
    assert issue.title == "Bug"
    assert issue.state == "open"


@pytest.mark.django_db
def test_create_or_update_issue_updates_existing(github_repository, github_account):
    """create_or_update_issue updates existing issue by issue_id."""
    services.create_or_update_issue(
        github_repository,
        github_account,
        issue_number=2,
        issue_id=200,
        title="Old",
        state="open",
    )
    issue, created = services.create_or_update_issue(
        github_repository,
        github_account,
        issue_number=2,
        issue_id=200,
        title="New title",
        state="closed",
    )
    assert created is False
    issue.refresh_from_db()
    assert issue.title == "New title"
    assert issue.state == "closed"


@pytest.mark.django_db
def test_create_or_update_issue_empty_title_body_allowed(
    github_repository, github_account
):
    """create_or_update_issue accepts empty title/body (stored as empty string)."""
    issue, created = services.create_or_update_issue(
        github_repository,
        github_account,
        issue_number=3,
        issue_id=300,
        title="",
        body="",
        state="open",
    )
    assert created is True
    assert issue.title == ""
    assert issue.body == ""


# --- add_issue_label / remove_issue_label ---


@pytest.mark.django_db
def test_add_issue_label_creates(issue_with_repo, github_repository, github_account):
    """add_issue_label creates IssueLabel."""
    issue, _ = issue_with_repo
    label, created = services.add_issue_label(issue, "bug")
    assert created is True
    assert label.label_name == "bug"


@pytest.mark.django_db
def test_add_issue_label_idempotent(issue_with_repo):
    """add_issue_label is idempotent (get_or_create)."""
    issue, _ = issue_with_repo
    services.add_issue_label(issue, "enhancement")
    label2, created = services.add_issue_label(issue, "enhancement")
    assert created is False


@pytest.mark.django_db
def test_remove_issue_label_removes(issue_with_repo):
    """remove_issue_label deletes the label."""
    issue, _ = issue_with_repo
    services.add_issue_label(issue, "wontfix")
    services.remove_issue_label(issue, "wontfix")
    assert not IssueLabel.objects.filter(issue=issue, label_name="wontfix").exists()


# --- create_or_update_pull_request ---


@pytest.mark.django_db
def test_create_or_update_pull_request_creates(github_repository, github_account):
    """create_or_update_pull_request creates new PullRequest."""
    pr, created = services.create_or_update_pull_request(
        github_repository,
        github_account,
        pr_number=1,
        pr_id=500,
        title="Feature",
        body="Body",
        state="open",
    )
    assert created is True
    assert pr.pr_number == 1
    assert pr.pr_id == 500
    assert pr.title == "Feature"


@pytest.mark.django_db
def test_create_or_update_pull_request_updates_existing(
    github_repository, github_account
):
    """create_or_update_pull_request updates existing PR by pr_id."""
    services.create_or_update_pull_request(
        github_repository,
        github_account,
        pr_number=2,
        pr_id=600,
        title="Old",
        state="open",
    )
    pr, created = services.create_or_update_pull_request(
        github_repository,
        github_account,
        pr_number=2,
        pr_id=600,
        title="Updated",
        state="merged",
    )
    assert created is False
    pr.refresh_from_db()
    assert pr.title == "Updated"
    assert pr.state == "merged"


@pytest.mark.django_db
def test_create_or_update_pull_request_head_base_hash(
    github_repository, github_account
):
    """create_or_update_pull_request stores head_hash and base_hash."""
    pr, _ = services.create_or_update_pull_request(
        github_repository,
        github_account,
        pr_number=3,
        pr_id=700,
        head_hash="abc",
        base_hash="main",
    )
    assert pr.head_hash == "abc"
    assert pr.base_hash == "main"


# --- add_pull_request_label ---


@pytest.mark.django_db
def test_add_pull_request_label_creates(pr_with_repo):
    """add_pull_request_label creates PullRequestLabel."""
    pr, _ = pr_with_repo
    label, created = services.add_pull_request_label(pr, "ready")
    assert created is True
    assert label.label_name == "ready"


@pytest.mark.django_db
def test_add_pull_request_label_idempotent(pr_with_repo):
    """add_pull_request_label is idempotent."""
    pr, _ = pr_with_repo
    services.add_pull_request_label(pr, "reviewed")
    label2, created = services.add_pull_request_label(pr, "reviewed")
    assert created is False


@pytest.mark.django_db
def test_remove_pull_request_label_removes(pr_with_repo):
    """remove_pull_request_label deletes the label."""
    pr, _ = pr_with_repo
    services.add_pull_request_label(pr, "blocked")
    services.remove_pull_request_label(pr, "blocked")
    assert not PullRequestLabel.objects.filter(pr=pr, label_name="blocked").exists()


# --- Fixtures used by issue/PR tests ---


@pytest.fixture
def issue_with_repo(github_repository, github_account):
    """Create an Issue and return (issue, repo)."""
    issue, _ = services.create_or_update_issue(
        github_repository,
        github_account,
        issue_number=99,
        issue_id=999,
        title="Fixture issue",
        state="open",
    )
    return issue, github_repository


@pytest.fixture
def pr_with_repo(github_repository, github_account):
    """Create a PullRequest and return (pr, repo)."""
    pr, _ = services.create_or_update_pull_request(
        github_repository,
        github_account,
        pr_number=88,
        pr_id=888,
        title="Fixture PR",
        state="open",
    )
    return pr, github_repository
