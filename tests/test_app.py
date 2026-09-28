from io import BytesIO

from PIL import Image

from database import get_db, query_db


PASSWORD = "CampusPassword123"


def register_payload(**overrides):
    values = {
        "name": "New Student",
        "email": "new.student@example.edu",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
    }
    values.update(overrides)
    return values


def test_registration_creates_student_and_rejects_invalid_or_duplicate_email(client, app, helpers, login_user):
    response = client.post("/register", data=register_payload())
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/my-reports")
    with app.app_context():
        user = query_db("SELECT role FROM users WHERE email = ?", ("new.student@example.edu",), one=True)
        assert user["role"] == "student"

    client.post("/logout")
    assert client.post("/register", data=register_payload()).status_code == 400
    assert client.post("/register", data=register_payload(email="bad-email")).status_code == 400
    assert client.post("/register", data=register_payload(password="short", confirm_password="short")).status_code == 400


def test_login_logout_and_bad_password(client, helpers, login_user):
    helpers["create_user"]()
    assert login_user(client).status_code == 302
    assert client.get("/my-reports").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/my-reports").status_code == 302
    response = client.post("/login", data={"email": "student@example.edu", "password": "incorrect"})
    assert response.status_code == 401
    assert b"incorrect" in response.data.lower()


def test_role_based_access_control_for_admin_pages_and_updates(client, helpers, login_user):
    assert client.get("/report").status_code == 302
    assert client.get("/admin").status_code == 302
    assert client.get("/api/admin/analytics").status_code == 401
    helpers["create_user"]()
    login_user(client)
    assert client.get("/admin").status_code == 403
    assert client.get("/admin/analytics").status_code == 403
    assert client.get("/api/admin/analytics").status_code == 403
    assert client.get("/api/admin/issues").status_code == 403
    assert client.patch("/api/issues/1", json={"priority": "high"}).status_code == 403

    client.post("/logout")
    helpers["create_user"](name="Admin", email="admin@example.edu", role="admin")
    login_user(client, "admin@example.edu")
    assert client.get("/admin").status_code == 200
    assert client.get("/admin/analytics").status_code == 200


def test_issue_submission_persists_and_invalid_fields_are_rejected(client, app, helpers, login_user):
    helpers["create_user"]()
    login_user(client)
    location = helpers["location_id"]()
    data = {
        "title": "Broken chair",
        "description": "A chair is broken in the classroom.",
        "category": "Furniture",
        "location_id": str(location),
    }
    response = client.post("/report", data=data)
    assert response.status_code == 302
    assert client.post("/report", data={**data, "title": "", "location_id": "invalid"}).status_code == 400
    assert client.post("/report", data={**data, "category": "Unknown"}).status_code == 400
    with app.app_context():
        rows = query_db("SELECT title FROM issues")
        assert [row["title"] for row in rows] == ["Broken chair"]


def test_valid_image_upload_is_sanitized_stored_privately_and_malformed_upload_rejected(
    client, app, helpers, login_user, tmp_path
):
    helpers["create_user"]()
    login_user(client)
    location = helpers["location_id"]()
    fields = {
        "title": "Leaking pipe",
        "description": "Water is leaking.",
        "category": "Water",
        "location_id": str(location),
    }
    png = BytesIO()
    Image.new("RGB", (12, 12), "red").save(png, format="PNG")
    response = client.post(
        "/report", data={**fields, "photo": (BytesIO(png.getvalue()), "issue.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        issue = query_db("SELECT issue_id, photo_path FROM issues", one=True)
        path = tmp_path / "private-uploads" / issue["photo_path"].split("/", 1)[1]
        assert path.is_file()
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert client.get(f"/issues/{issue['issue_id']}/photo").status_code == 200

    bad_type = client.post(
        "/report", data={**fields, "title": "Second report", "photo": (BytesIO(b"not an image"), "bad.png")},
        content_type="multipart/form-data",
    )
    wrong_extension = client.post(
        "/report", data={**fields, "title": "Third report", "photo": (BytesIO(png.getvalue()), "issue.gif")},
        content_type="multipart/form-data",
    )
    assert bad_type.status_code == 400
    assert wrong_extension.status_code == 400


def test_student_report_listing_filters_and_ownership(client, app, helpers, login_user):
    first = helpers["create_user"]()
    second = helpers["create_user"](name="Other", email="other@example.edu")
    first_issue = helpers["create_report"](first, title="Loose chair", category="Furniture")
    helpers["create_report"](first, title="Broken light", category="Lighting", status="resolved")
    other_issue = helpers["create_report"](second, title="Private report")

    login_user(client)
    listing = client.get("/api/my-reports").get_json()
    assert listing["meta"]["total"] == 2
    assert len(listing["data"]["reports"]) == 2
    filtered = client.get("/api/my-reports?category=Furniture&status=pending").get_json()
    assert [row["issue_id"] for row in filtered["data"]["reports"]] == [first_issue]
    assert client.get(f"/api/issues/{first_issue}").status_code == 200
    assert client.get(f"/api/issues/{other_issue}").status_code == 404
    assert client.get(f"/issues/{other_issue}").status_code == 404
    assert client.get("/api/my-reports?category=not-a-category").status_code == 400
    assert client.get("/api/my-reports?status=not-a-status").status_code == 400

    client.post("/logout")
    helpers["create_user"](name="Admin", email="admin@example.edu", role="admin")
    login_user(client, "admin@example.edu")
    assert client.get("/api/my-reports").get_json()["meta"]["total"] == 3
    assert client.get(f"/api/issues/{other_issue}").status_code == 200


def test_admin_status_update_validation_missing_issue_and_history(client, app, helpers, login_user):
    student = helpers["create_user"]()
    issue_id = helpers["create_report"](student)
    helpers["create_user"](name="Admin", email="admin@example.edu", role="admin")
    login_user(client, "admin@example.edu")

    assert client.patch("/api/issues/9999", json={"priority": "high"}).status_code == 404
    assert client.patch(f"/api/issues/{issue_id}", json={"status": "resolved"}).status_code == 400
    assert client.patch(f"/api/issues/{issue_id}", json={"status": "unknown"}).status_code == 400
    updated = client.patch(
        f"/api/issues/{issue_id}", json={"status": "resolved", "comment": "Repair completed."}
    )
    assert updated.status_code == 200
    assert updated.get_json()["data"]["status"] == "resolved"
    history = client.get(f"/api/issues/{issue_id}/history").get_json()["data"]["history"]
    assert [row["new_status"] for row in history] == ["submitted", "resolved"]
    assert history[-1]["comment"] == "Repair completed."
    assert client.get("/api/issues/9999/history").status_code == 404


def test_analytics_metrics_categories_hotspots_and_date_validation(client, app, helpers, login_user):
    student = helpers["create_user"]()
    unresolved_id = helpers["create_report"](student, title="Loose chair", category="Furniture")
    resolved_id = helpers["create_report"](student, title="Pipe fixed", category="Water")
    helpers["create_user"](name="Admin", email="admin@example.edu", role="admin")
    with app.app_context():
        db = get_db()
        db.execute("UPDATE issues SET created_at = '2025-01-10 10:00:00' WHERE issue_id IN (?, ?)",
                   (unresolved_id, resolved_id))
        db.execute("UPDATE issues SET status = 'resolved' WHERE issue_id = ?", (resolved_id,))
        db.execute(
            "UPDATE issue_history SET updated_at = '2025-01-10 12:00:00' "
            "WHERE issue_id = ? AND new_status = 'submitted'", (resolved_id,),
        )
        db.execute(
            "INSERT INTO issue_history (issue_id, old_status, new_status, updated_by, updated_at, comment) "
            "VALUES (?, 'submitted', 'resolved', ?, '2025-01-10 14:00:00', 'Done')",
            (resolved_id, 1),
        )
        db.commit()

    login_user(client, "admin@example.edu")
    result = client.get("/api/admin/analytics?start_date=2025-01-01&end_date=2025-01-31")
    assert result.status_code == 200
    payload = result.get_json()["data"]
    assert payload["metrics"]["total"] == 2
    assert payload["metrics"]["unresolved"] == 1
    assert payload["metrics"]["resolution_rate"] == 50.0
    assert payload["metrics"]["average_resolution_hours"] == 4.0
    assert payload["categories"]
    assert payload["monthly"] == [{"month": "2025-01", "count": 2}]
    assert payload["hotspots"][0]["unresolved"] == 1
    assert client.get("/api/admin/analytics?start_date=not-a-date").status_code == 400
    assert client.get("/api/admin/analytics?start_date=2025-02-01&end_date=2025-01-01").status_code == 400
