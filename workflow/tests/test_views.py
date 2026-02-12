"""Minimal view tests (admin is the only app-served URL). Uses django-test-plus tp fixture."""
import pytest


@pytest.mark.django_db
def test_admin_login_redirect(tp):
    """GET /admin/ redirects to login (302) when not authenticated."""
    tp.get("/admin/")
    tp.response_302()


@pytest.mark.django_db
def test_admin_login_page_reachable(tp):
    """GET /admin/login/ returns 200."""
    tp.get("/admin/login/")
    tp.response_200()


@pytest.mark.django_db
def test_admin_login_page_contains_login_form(tp):
    """GET /admin/login/ returns a page that includes login form (username/password or csrf)."""
    tp.get("/admin/login/")
    tp.response_200()
    content = tp.last_response.content.decode("utf-8").lower()
    # Django admin login page has either a login form with username/password or "log in" text
    assert "log in" in content or "username" in content or "password" in content or "csrf" in content
