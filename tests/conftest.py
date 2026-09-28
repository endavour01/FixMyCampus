"""Shared pytest setup with an isolated bootstrap database before app import."""

import os
import tempfile

import pytest


# app.py initializes the database when imported. Point that startup database at
# a disposable temp directory so even import-time initialization cannot touch
# the development database.
_bootstrap_directory = tempfile.TemporaryDirectory(prefix="fixmycampus-pytest-")
os.environ["FIX_MY_CAMPUS_DATABASE"] = os.path.join(_bootstrap_directory.name, "bootstrap.sqlite")
os.environ["FIX_MY_CAMPUS_UPLOAD_FOLDER"] = os.path.join(_bootstrap_directory.name, "uploads")

from app import app as flask_app  # noqa: E402
from database import create_issue, get_db, init_db, query_db  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    database_path = tmp_path / "test-campus.sqlite"
    upload_path = tmp_path / "private-uploads"
    monkeypatch.setitem(flask_app.config, "DATABASE", str(database_path))
    monkeypatch.setitem(flask_app.config, "UPLOAD_FOLDER", str(upload_path))
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(flask_app.config, "SECRET_KEY", "pytest-only-secret")
    with flask_app.app_context():
        init_db()
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def helpers(app):
    def create_user(name="Test Student", email="student@example.edu", role="student", password="CampusPassword123"):
        with app.app_context():
            cursor = get_db().execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                (name, email, generate_password_hash(password), role),
            )
            get_db().commit()
            return cursor.lastrowid

    def location_id(index=0):
        with app.app_context():
            row = query_db(
                "SELECT location_id FROM locations ORDER BY location_id LIMIT 1 OFFSET ?",
                (index,), one=True,
            )
            return row["location_id"]

    def create_report(user_id, title="Broken chair", category="Furniture", status=None, location=None):
        with app.app_context():
            issue_id = create_issue(
                user_id=user_id,
                title=title,
                description="A chair is broken in the room.",
                category=category,
                location_id=location or location_id(),
            )
            if status:
                get_db().execute("UPDATE issues SET status = ? WHERE issue_id = ?", (status, issue_id))
                get_db().commit()
            return issue_id

    return {"create_user": create_user, "location_id": location_id, "create_report": create_report}


def login(client, email="student@example.edu", password="CampusPassword123"):
    return client.post("/login", data={"email": email, "password": password})


@pytest.fixture
def login_user():
    return login
