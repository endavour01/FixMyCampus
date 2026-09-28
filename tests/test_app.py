from io import BytesIO
import json
import re

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


def test_page_routes_render_for_their_intended_roles(client, helpers, login_user):
    def assert_rendered_assets_exist(path):
        response = client.get(path)
        assert response.status_code == 200, path
        html = response.get_data(as_text=True)
        for asset in re.findall(r'(?:href|src)="([^"]+)"', html):
            if asset.startswith("/static/"):
                assert client.get(asset).status_code == 200, asset

    assert_rendered_assets_exist("/")
    assert_rendered_assets_exist("/register")
    assert_rendered_assets_exist("/login")
    student = helpers["create_user"]()
    issue_id = helpers["create_report"](student)
    login_user(client)
    assert_rendered_assets_exist("/report")
    assert_rendered_assets_exist("/my-reports")
    assert_rendered_assets_exist(f"/issues/{issue_id}")
    client.post("/logout")
    helpers["create_user"](name="Admin", email="admin@example.edu", role="admin")
    login_user(client, "admin@example.edu")
    for path in ("/admin", "/admin/analytics", "/admin/map", "/my-reports", f"/issues/{issue_id}"):
        assert_rendered_assets_exist(path)


def test_login_logout_and_bad_password(client, helpers, login_user):
    helpers["create_user"]()
    assert login_user(client).status_code == 302
    assert client.get("/my-reports").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/my-reports").status_code == 302
    response = client.post("/login", data={"email": "student@example.edu", "password": "incorrect"})
    assert response.status_code == 401
    assert b"incorrect" in response.data.lower()


def test_csrf_rejects_mutating_post_without_token(client, app, monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    response = client.post("/login", data={"email": "student@example.edu", "password": PASSWORD})
    assert response.status_code == 400


def test_admin_cli_creates_first_admin_and_refuses_a_second(app):
    runner = app.test_cli_runner()
    created = runner.invoke(
        args=["create-admin"],
        input=f"Campus Admin\nadmin@example.edu\n{PASSWORD}\n{PASSWORD}\n",
    )
    assert created.exit_code == 0, created.output
    with app.app_context():
        admin = query_db("SELECT role FROM users WHERE email = ?", ("admin@example.edu",), one=True)
        assert admin["role"] == "admin"

    second = runner.invoke(args=["create-admin"], input="Another Admin\nanother@example.edu\n")
    assert second.exit_code != 0
    assert "already exists" in second.output


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
    helpers["create_user"](name="Other Student", email="other@example.edu")
    client.post("/logout")
    login_user(client, "other@example.edu")
    assert client.get(f"/issues/{issue['issue_id']}/photo").status_code == 404

    client.post("/logout")
    login_user(client)
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


def test_admin_issue_api_filters_pagination_and_dashboard_fields(client, helpers, login_user):
    student = helpers["create_user"]()
    issue_id = helpers["create_report"](student, title="Leaking sink", category="Water")
    helpers["create_report"](student, title="Broken chair", category="Furniture")
    helpers["create_user"](name="Admin", email="admin@example.edu", role="admin")
    login_user(client, "admin@example.edu")

    response = client.get("/api/admin/issues?category=Water&status=pending&page=1&per_page=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["meta"]["total"] == 1
    assert payload["meta"]["pages"] == 1
    assert payload["data"]["issues"][0]["issue_id"] == issue_id
    assert payload["data"]["issues"][0]["description"] == "A chair is broken in the room."
    assert payload["meta"]["filters"]["locations"]
    assert client.get("/api/admin/issues?per_page=101").status_code == 400
    assert client.get("/api/admin/issues?location=invalid").status_code == 400


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


def test_admin_map_page_filters_reports_and_exposes_only_configured_coordinates(
    client, app, helpers, login_user, monkeypatch
):
    student = helpers["create_user"]()
    location_id = helpers["location_id"]()
    pending_issue = helpers["create_report"](student, title="Chair problem", category="Furniture", location=location_id)
    resolved_issue = helpers["create_report"](student, title="Old light issue", category="Lighting", status="resolved", location=location_id)
    helpers["create_user"](name="Admin", email="admin@example.edu", role="admin")
    with app.app_context():
        location = query_db(
            "SELECT building_name, area_name FROM locations WHERE location_id = ?",
            (location_id,), one=True,
        )
    key = f"{location['building_name']}|{location['area_name']}"
    monkeypatch.setitem(app.config, "CAMPUS_LOCATION_COORDINATES", json.dumps({key: [26.7759, 75.8745]}))

    login_user(client, "admin@example.edu")
    assert client.get("/admin/map").status_code == 200
    filtered_response = client.get("/api/admin/map?category=Furniture&status=pending")
    assert filtered_response.status_code == 200
    locations = filtered_response.get_json()["data"]["locations"]
    selected_location = next(item for item in locations if item["location_id"] == location_id)
    assert (selected_location["latitude"], selected_location["longitude"]) == (26.7759, 75.8745)
    assert selected_location["unresolved_count"] == 1
    assert [item["issue_id"] for item in selected_location["reports"]] == [pending_issue]
    assert "user_id" not in selected_location["reports"][0]
    assert "email" not in selected_location["reports"][0]

    resolved = client.get("/api/admin/map?status=resolved").get_json()["data"]["locations"]
    selected_resolved = next(item for item in resolved if item["location_id"] == location_id)
    assert [item["issue_id"] for item in selected_resolved["reports"]] == [resolved_issue]
    assert selected_resolved["unresolved_count"] == 1
    assert client.get("/api/admin/map?status=invalid").status_code == 400
