"""Minimal view tests (admin is the only app-served URL). Uses pytest-django client fixture."""

import pytest


@pytest.mark.django_db
def test_admin_login_redirect(client):
    """GET /admin/ redirects to login (302) when not authenticated."""
    response = client.get("/admin/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_admin_login_page_reachable(client):
    """GET /admin/login/ returns 200."""
    response = client.get("/admin/login/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_login_page_contains_login_form(client):
    """GET /admin/login/ returns a page that includes login form (username/password or csrf)."""
    response = client.get("/admin/login/")
    assert response.status_code == 200
    content = response.content.decode("utf-8").lower()
    # Django admin login page has either a login form with username/password or "log in" text
    assert (
        "log in" in content
        or "username" in content
        or "password" in content
        or "csrf" in content
    )
