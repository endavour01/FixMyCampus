import click
import difflib
import json
import os
import re
import secrets
import sqlite3
import uuid
import warnings
from io import BytesIO
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urljoin, urlparse

from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_wtf.csrf import CSRFProtect
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from PIL import Image, ImageOps, UnidentifiedImageError

from database import (
    create_issue,
    get_db,
    init_app,
    init_db,
    query_db,
)

ISSUE_CATEGORIES = (
    "Wi-Fi",
    "Electricity",
    "Water",
    "Cleanliness",
    "Furniture",
    "Lighting",
    "Classroom Equipment",
    "Other",
)
REPORT_STATUS_FILTERS = {
    "pending": ("submitted", "under_review"),
    "in_progress": ("in_progress",),
    "resolved": ("resolved", "closed"),
}
ADMIN_STATUS_TRANSITIONS = {
    "pending": {"pending", "in_progress", "resolved"},
    "in_progress": {"in_progress", "resolved"},
    "resolved": {"resolved", "in_progress"},
}
ADMIN_PRIORITIES = {"low", "normal", "high", "critical"}
EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}$",
    re.IGNORECASE,
)
MAX_PHOTO_SIZE = 5 * 1024 * 1024
ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PHOTO_SIGNATURES = {
    ".jpg": lambda content: content.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda content: content.startswith(b"\xff\xd8\xff"),
    ".png": lambda content: content.startswith(b"\x89PNG\r\n\x1a\n"),
    ".webp": lambda content: content[:4] == b"RIFF" and content[8:12] == b"WEBP",
}


class UploadValidationError(ValueError):
    """A user-facing validation failure for an uploaded image."""

app = Flask(__name__, instance_relative_config=True)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
    DATABASE=os.path.join(app.instance_path, "campus.db"),
    UPLOAD_FOLDER=os.path.join(app.instance_path, "uploads"),
    MAX_CONTENT_LENGTH=MAX_PHOTO_SIZE + 256 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    COLLEGE_EMAIL_DOMAIN=os.environ.get("COLLEGE_EMAIL_DOMAIN", "").strip().lower().lstrip("@"),
    CAMPUS_LOCATION_COORDINATES=os.environ.get("CAMPUS_LOCATION_COORDINATES", "{}"),
)
csrf = CSRFProtect(app)
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))

os.makedirs(app.instance_path, exist_ok=True)
init_app(app)
with app.app_context():
    init_db()


@app.route("/")
def home():
    return render_template("index.html")


def get_current_user():
    """Load the account stored in the signed Flask session."""
    try:
        user_id = int(session.get("user_id"))
    except (TypeError, ValueError):
        return None

    user = query_db(
        "SELECT user_id, name, email, role FROM users WHERE user_id = ?",
        (user_id,),
        one=True,
    )
    if user is None:
        session.clear()
    return user


def login_required(view):
    """Require a valid login, returning JSON errors for API endpoints."""
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = get_current_user()
        if user is None:
            if request.path.startswith("/api/"):
                return api_error("authentication_required", "Sign in to continue.", 401)
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=next_url))
        g.current_user = user
        return view(*args, **kwargs)

    return wrapped_view


def roles_required(*allowed_roles):
    """Restrict a private view to the listed account roles."""
    def decorate(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            user = getattr(g, "current_user", None) or get_current_user()
            if user is None:
                abort(401)
            if user["role"] not in allowed_roles:
                if request.path.startswith("/api/"):
                    return api_error("forbidden", "You do not have permission to access this resource.", 403)
                abort(403)
            g.current_user = user
            return view(*args, **kwargs)

        return wrapped_view

    return decorate


def api_error(code, message, status_code):
    return jsonify({"error": {"code": code, "message": message}}), status_code


def valid_college_email(email):
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        return False
    required_domain = app.config["COLLEGE_EMAIL_DOMAIN"]
    return not required_domain or email.rsplit("@", 1)[1].lower() == required_domain


def password_error(password):
    if len(password) < 12:
        return "Use at least 12 characters for your password."
    if len(password) > 128:
        return "Use no more than 128 characters for your password."
    if not any(character.isalpha() for character in password) or not any(character.isdigit() for character in password):
        return "Include at least one letter and one number."
    return None


def sanitize_uploaded_image(content, extension):
    """Decode and re-encode a bounded raster image, discarding untrusted metadata."""
    expected_formats = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
    expected_format = expected_formats.get(extension)
    if not expected_format:
        raise UploadValidationError("Choose a JPEG, PNG, or WebP image.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != expected_format:
                    raise UploadValidationError("The selected file does not match its image type.")
                if image.width * image.height > 20_000_000:
                    raise UploadValidationError("The image dimensions are too large.")
                if getattr(image, "n_frames", 1) != 1:
                    raise UploadValidationError("Animated images are not supported.")
                image.verify()

            with Image.open(BytesIO(content)) as image:
                image = ImageOps.exif_transpose(image)
                image.load()
                if expected_format == "JPEG":
                    image = image.convert("RGB")
                elif expected_format == "PNG" and image.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
                    image = image.convert("RGBA")
                elif expected_format == "WEBP" and image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA")

                output = BytesIO()
                save_options = {"quality": 90, "method": 4} if expected_format == "WEBP" else {}
                if expected_format == "JPEG":
                    save_options = {"quality": 90, "optimize": True}
                image.save(output, format=expected_format, **save_options)
                sanitized = output.getvalue()
                if len(sanitized) > MAX_PHOTO_SIZE:
                    raise UploadValidationError("The processed image must be 5 MB or smaller.")
                return sanitized
    except UploadValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise UploadValidationError("Choose a valid JPEG, PNG, or WebP image.") from error


def migrate_legacy_uploaded_photos():
    """Move referenced uploads out of Flask's public static directory."""
    public_uploads = (Path(app.static_folder) / "uploads").resolve()
    private_uploads = Path(app.config["UPLOAD_FOLDER"]).resolve()
    private_uploads.mkdir(parents=True, exist_ok=True)
    for issue in query_db("SELECT issue_id, photo_path FROM issues WHERE photo_path IS NOT NULL"):
        stored_path = issue["photo_path"] or ""
        parts = Path(stored_path).parts
        if len(parts) != 2 or parts[0] != "uploads" or "\\" in stored_path:
            continue
        filename = parts[1]
        extension = Path(filename).suffix.lower()
        if Path(filename).name != filename or extension not in ALLOWED_PHOTO_EXTENSIONS:
            continue
        source = (public_uploads / filename).resolve()
        destination = (private_uploads / filename).resolve()
        try:
            source.relative_to(public_uploads)
            destination.relative_to(private_uploads)
        except ValueError:
            continue
        if not source.is_file() or destination.exists():
            continue
        try:
            sanitized = sanitize_uploaded_image(source.read_bytes(), extension)
        except (OSError, ValueError):
            continue
        destination.write_bytes(sanitized)
        source.unlink()


def is_safe_redirect(target):
    if not target:
        return False
    reference = urlparse(request.host_url)
    destination = urlparse(urljoin(request.host_url, target))
    return destination.scheme in {"http", "https"} and reference.netloc == destination.netloc


def start_user_session(user):
    session.clear()
    session.permanent = True
    session["user_id"] = user["user_id"]


@app.context_processor
def inject_current_user():
    return {"current_user": get_current_user()}


@app.before_request
def block_public_issue_uploads():
    """Keep legacy upload URLs private while issue photos move out of static/."""
    static_file = request.view_args.get("filename", "") if request.endpoint == "static" and request.view_args else ""
    if static_file == "uploads" or static_file.startswith("uploads/"):
        abort(404)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@app.route("/register", methods=["GET", "POST"])
def register():
    if get_current_user() is not None:
        return redirect(url_for("my_reports"))

    form_data = {"name": "", "email": ""}
    errors = {}
    if request.method == "POST":
        form_data = {
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
        }
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not form_data["name"]:
            errors["name"] = "Enter your name."
        elif len(form_data["name"]) > 100:
            errors["name"] = "Your name must be 100 characters or fewer."

        if not valid_college_email(form_data["email"]):
            errors["email"] = "Enter a valid college email address."
        elif query_db(
            "SELECT user_id FROM users WHERE email = ?", (form_data["email"],), one=True
        ):
            errors["email"] = "An account with this email already exists."

        password_problem = password_error(password)
        if password_problem:
            errors["password"] = password_problem
        if password != confirm_password:
            errors["confirm_password"] = "The passwords do not match."

        if not errors:
            try:
                cursor = query_db(
                    "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                    (form_data["name"], form_data["email"], generate_password_hash(password), "student"),
                )
            except sqlite3.IntegrityError:
                get_db().rollback()
                errors["email"] = "An account with this email already exists."
            else:
                get_db().commit()
                user = query_db(
                    "SELECT user_id FROM users WHERE email = ?", (form_data["email"],), one=True
                )
                start_user_session(user)
                return redirect(url_for("my_reports"))

    return render_template(
        "register.html",
        form_data=form_data,
        errors=errors,
        college_email_domain=app.config["COLLEGE_EMAIL_DOMAIN"],
    ), 400 if errors else 200


@app.route("/login", methods=["GET", "POST"])
def login():
    current_user = get_current_user()
    if current_user is not None:
        return redirect(url_for("my_reports") if current_user["role"] == "student" else url_for("home"))

    email = ""
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = query_db(
            "SELECT user_id, name, email, password_hash, role FROM users WHERE email = ?",
            (email,),
            one=True,
        )
        stored_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
        password_matches = check_password_hash(stored_hash, password)
        if user is None or not password_matches:
            error = "The email or password is incorrect."
        else:
            start_user_session(user)
            target = request.form.get("next") or request.args.get("next")
            if is_safe_redirect(target):
                return redirect(target)
            return redirect(url_for("my_reports") if user["role"] == "student" else url_for("home"))

    return render_template(
        "login.html",
        email=email,
        error=error,
        next_url=request.args.get("next", ""),
    ), 401 if error else 200


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.cli.command("create-admin")
def create_admin_command():
    """Create the first admin interactively without putting credentials in shell history."""
    if query_db("SELECT user_id FROM users WHERE role = ? LIMIT 1", ("admin",), one=True):
        raise click.ClickException("An admin account already exists; this command only creates the first admin.")

    name = click.prompt("Admin name").strip()
    email = click.prompt("College email").strip().lower()
    if not name or len(name) > 100:
        raise click.ClickException("Name must be between 1 and 100 characters.")
    if not valid_college_email(email):
        raise click.ClickException("Enter a valid college email address.")
    if query_db("SELECT user_id FROM users WHERE email = ?", (email,), one=True):
        raise click.ClickException("An account with this email already exists.")

    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    problem = password_error(password)
    if problem:
        raise click.ClickException(problem)

    query_db(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (name, email, generate_password_hash(password), "admin"),
    )
    get_db().commit()
    click.echo("The first admin account has been created.")


@app.cli.command("create-maintenance")
def create_maintenance_command():
    """Create an assignable maintenance account using interactive prompts."""
    name = click.prompt("Maintenance staff name").strip()
    email = click.prompt("College email").strip().lower()
    if not name or len(name) > 100:
        raise click.ClickException("Name must be between 1 and 100 characters.")
    if not valid_college_email(email):
        raise click.ClickException("Enter a valid college email address.")
    if query_db("SELECT user_id FROM users WHERE email = ?", (email,), one=True):
        raise click.ClickException("An account with this email already exists.")

    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    problem = password_error(password)
    if problem:
        raise click.ClickException(problem)

    query_db(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (name, email, generate_password_hash(password), "maintenance"),
    )
    get_db().commit()
    click.echo("The maintenance account has been created and can be assigned reports.")


@app.route("/my-reports")
@login_required
@roles_required("student", "admin")
def my_reports():
    return render_template(
        "my_reports.html",
        categories=ISSUE_CATEGORIES,
        is_admin=g.current_user["role"] == "admin",
    )


def issue_for_user(issue_id, user):
    query = """
        SELECT
            issues.*,
            locations.building_name,
            locations.area_name,
            locations.floor_number
            , assignee.name AS assigned_name
        FROM issues
        JOIN locations ON locations.location_id = issues.location_id
        LEFT JOIN users AS assignee ON assignee.user_id = issues.assigned_to
        WHERE issues.issue_id = ?
    """
    parameters = [issue_id]
    if user["role"] == "student":
        query += " AND issues.user_id = ?"
        parameters.append(user["user_id"])
    return query_db(query, parameters, one=True)


@app.route("/admin")
@login_required
@roles_required("admin")
def admin_dashboard():
    return render_template(
        "admin_dashboard.html",
        categories=ISSUE_CATEGORIES,
        is_admin=True,
    )


@app.route("/admin/analytics")
@login_required
@roles_required("admin")
def admin_analytics():
    return render_template("admin_analytics.html")


@app.route("/api/admin/analytics")
@login_required
@roles_required("admin")
def admin_analytics_api():
    """Return analytics calculated from reports and their recorded status history."""
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    for label, value in (("start date", start_date), ("end date", end_date)):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                return api_error("invalid_date", f"Enter a valid {label} in YYYY-MM-DD format.", 400)
            if len(value) != 10:
                return api_error("invalid_date", f"Enter a valid {label} in YYYY-MM-DD format.", 400)
    if start_date and end_date and start_date > end_date:
        return api_error("invalid_date_range", "The start date must be on or before the end date.", 400)

    conditions = []
    parameters = []
    if start_date:
        conditions.append("date(issues.created_at) >= date(?)")
        parameters.append(start_date)
    if end_date:
        conditions.append("date(issues.created_at) <= date(?)")
        parameters.append(end_date)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    metrics = query_db(
        f"""
        WITH resolved_times AS (
            SELECT issue_id, MIN(updated_at) AS resolved_at
            FROM issue_history
            WHERE event_type = 'status' AND new_status IN ('resolved', 'closed')
            GROUP BY issue_id
        )
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN issues.status NOT IN ('resolved', 'closed') THEN 1 ELSE 0 END), 0) AS unresolved,
            COALESCE(SUM(CASE WHEN issues.status IN ('resolved', 'closed') THEN 1 ELSE 0 END), 0) AS resolved,
            AVG(CASE WHEN resolved_times.resolved_at IS NOT NULL
                THEN (julianday(resolved_times.resolved_at) - julianday(issues.created_at)) * 24.0
                END) AS average_resolution_hours
        FROM issues
        LEFT JOIN resolved_times ON resolved_times.issue_id = issues.issue_id
        {where_clause}
        """,
        parameters,
        one=True,
    )

    by_category = query_db(
        f"""SELECT issues.category AS label, COUNT(*) AS count
            FROM issues {where_clause}
            GROUP BY issues.category ORDER BY count DESC, label""",
        parameters,
    )
    by_location = query_db(
        f"""SELECT locations.building_name, locations.area_name,
                   locations.floor_number, COUNT(issues.issue_id) AS count
            FROM issues
            JOIN locations ON locations.location_id = issues.location_id
            {where_clause}
            GROUP BY locations.location_id
            ORDER BY count DESC, locations.building_name, locations.area_name""",
        parameters,
    )
    monthly = query_db(
        f"""SELECT strftime('%Y-%m', issues.created_at) AS month, COUNT(*) AS count
            FROM issues {where_clause}
            GROUP BY strftime('%Y-%m', issues.created_at)
            ORDER BY month""",
        parameters,
    )
    hotspot_conditions = [*conditions, "issues.status NOT IN ('resolved', 'closed')"]
    hotspots = query_db(
        f"""SELECT locations.building_name, locations.area_name,
                   locations.floor_number, COUNT(*) AS unresolved
            FROM issues
            JOIN locations ON locations.location_id = issues.location_id
            WHERE {' AND '.join(hotspot_conditions)}
            GROUP BY locations.location_id
            ORDER BY unresolved DESC, locations.building_name, locations.area_name
            LIMIT 10""",
        parameters,
    )

    total = metrics["total"] or 0
    resolved = metrics["resolved"] or 0
    return jsonify({
        "data": {
            "metrics": {
                "total": total,
                "unresolved": metrics["unresolved"] or 0,
                "resolution_rate": round((resolved / total) * 100, 1) if total else 0,
                "average_resolution_hours": round(metrics["average_resolution_hours"], 1)
                    if metrics["average_resolution_hours"] is not None else None,
            },
            "categories": [dict(row) for row in by_category],
            "locations": [dict(row) for row in by_location],
            "monthly": [dict(row) for row in monthly],
            "hotspots": [dict(row) for row in hotspots],
        },
        "meta": {"start_date": start_date or None, "end_date": end_date or None},
    })


@app.route("/admin/map")
@login_required
@roles_required("admin")
def admin_issue_map():
    return render_template(
        "admin_map.html",
        categories=ISSUE_CATEGORIES,
        map_center=(26.7759, 75.8745),
    )


@app.route("/api/admin/map")
@login_required
@roles_required("admin")
def admin_issue_map_api():
    """Return campus location aggregates and reports without reporter identity data."""
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "all").strip()
    if category and category not in ISSUE_CATEGORIES:
        return api_error("invalid_category", "Choose a valid issue category.", 400)
    status_groups = {
        "all": (),
        "pending": ("submitted", "under_review"),
        "in_progress": ("in_progress",),
        "resolved": ("resolved", "closed"),
    }
    if status not in status_groups:
        return api_error("invalid_status", "Choose a valid status filter.", 400)

    try:
        configured_coordinates = json.loads(app.config["CAMPUS_LOCATION_COORDINATES"] or "{}")
    except (TypeError, json.JSONDecodeError):
        configured_coordinates = {}
    if not isinstance(configured_coordinates, dict):
        configured_coordinates = {}

    locations = query_db(
        "SELECT location_id, building_name, area_name, floor_number FROM locations ORDER BY building_name, floor_number, area_name"
    )
    category_condition = " AND issues.category = ?" if category else ""
    category_parameters = [category] if category else []
    unresolved_rows = query_db(
        f"""SELECT location_id, COUNT(*) AS count FROM issues
            WHERE status NOT IN ('resolved', 'closed'){category_condition}
            GROUP BY location_id""",
        category_parameters,
    )
    unresolved_counts = {row["location_id"]: row["count"] for row in unresolved_rows}

    report_conditions = []
    report_parameters = []
    if category:
        report_conditions.append("category = ?")
        report_parameters.append(category)
    selected_statuses = status_groups[status]
    if selected_statuses:
        placeholders = ", ".join("?" for _ in selected_statuses)
        report_conditions.append(f"status IN ({placeholders})")
        report_parameters.extend(selected_statuses)
    report_where = f"WHERE {' AND '.join(report_conditions)}" if report_conditions else ""
    reports = query_db(
        f"""SELECT issue_id, location_id, title, category, status, created_at
            FROM issues {report_where}
            ORDER BY created_at DESC, issue_id DESC""",
        report_parameters,
    )
    reports_by_location = {}
    for issue in reports:
        reports_by_location.setdefault(issue["location_id"], []).append({
            "issue_id": issue["issue_id"],
            "title": issue["title"],
            "category": issue["category"],
            "status": issue["status"],
            "created_at": issue["created_at"],
        })

    data = []
    for location in locations:
        coordinate_key = f"{location['building_name']}|{location['area_name']}"
        coordinate = configured_coordinates.get(coordinate_key)
        latitude = longitude = None
        if (isinstance(coordinate, (list, tuple)) and len(coordinate) == 2
                and not any(isinstance(value, bool) for value in coordinate)):
            try:
                latitude, longitude = float(coordinate[0]), float(coordinate[1])
            except (TypeError, ValueError):
                latitude = longitude = None
            if (latitude is not None and longitude is not None
                    and (-90 <= latitude <= 90) and (-180 <= longitude <= 180)):
                pass
            else:
                latitude = longitude = None

        location_reports = reports_by_location.get(location["location_id"], [])
        data.append({
            "location_id": location["location_id"],
            "building_name": location["building_name"],
            "area_name": location["area_name"],
            "floor_number": location["floor_number"],
            "latitude": latitude,
            "longitude": longitude,
            "unresolved_count": unresolved_counts.get(location["location_id"], 0),
            "report_count": len(location_reports),
            "reports": location_reports[:25],
        })

    return jsonify({
        "data": {"locations": data},
        "meta": {"category": category or None, "status": status},
    })


@app.route("/api/admin/issues")
@login_required
@roles_required("admin")
def admin_issues_api():
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()
    location_value = request.args.get("location", "").strip()

    try:
        page = int(request.args.get("page", "1"))
        per_page = int(request.args.get("per_page", "20"))
    except ValueError:
        return api_error("invalid_pagination", "Page and page size must be numbers.", 400)
    if page < 1 or per_page < 1 or per_page > 100:
        return api_error("invalid_pagination", "Page must be positive and page size must be between 1 and 100.", 400)
    if len(search) > 120:
        return api_error("search_too_long", "Search text must be 120 characters or fewer.", 400)
    if category and category not in ISSUE_CATEGORIES:
        return api_error("invalid_category", "Choose a valid issue category.", 400)
    if status and status not in REPORT_STATUS_FILTERS:
        return api_error("invalid_status", "Choose a valid status filter.", 400)
    if priority and priority not in ADMIN_PRIORITIES:
        return api_error("invalid_priority", "Choose a valid priority filter.", 400)

    conditions = []
    parameters = []
    if category:
        conditions.append("issues.category = ?")
        parameters.append(category)
    if status:
        status_values = REPORT_STATUS_FILTERS[status]
        placeholders = ", ".join("?" for _ in status_values)
        conditions.append(f"issues.status IN ({placeholders})")
        parameters.extend(status_values)
    if priority:
        conditions.append("issues.priority = ?")
        parameters.append(priority)
    if location_value:
        try:
            location_id = int(location_value)
        except ValueError:
            return api_error("invalid_location", "Choose a valid location filter.", 400)
        conditions.append("issues.location_id = ?")
        parameters.append(location_id)
    if search:
        search_conditions = [
            "instr(CAST(issues.issue_id AS TEXT), ?) > 0",
            "instr(lower(issues.title), lower(?)) > 0",
            "instr(lower(issues.description), lower(?)) > 0",
            "instr(lower(issues.category), lower(?)) > 0",
            "instr(lower(locations.building_name), lower(?)) > 0",
            "instr(lower(locations.area_name), lower(?)) > 0",
            "instr(lower(COALESCE(users.name, '')), lower(?)) > 0",
        ]
        conditions.append(f"({' OR '.join(search_conditions)})")
        parameters.extend([search] * len(search_conditions))
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    summary = query_db(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN status IN ('submitted', 'under_review') THEN 1 ELSE 0 END), 0) AS pending,
            COALESCE(SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END), 0) AS in_progress,
            COALESCE(SUM(CASE WHEN status IN ('resolved', 'closed') THEN 1 ELSE 0 END), 0) AS resolved
        FROM issues
        """,
        one=True,
    )
    filtered_total = query_db(
        f"""
        SELECT COUNT(*) AS total
        FROM issues
        JOIN locations ON locations.location_id = issues.location_id
        LEFT JOIN users ON users.user_id = issues.user_id
        {where_clause}
        """,
        parameters,
        one=True,
    )["total"]
    pages = (filtered_total + per_page - 1) // per_page
    if pages and page > pages:
        page = pages

    issues = query_db(
        f"""
        SELECT
            issues.issue_id,
            issues.title,
            issues.category,
            issues.priority,
            issues.status,
            issues.created_at,
            locations.building_name,
            locations.area_name,
            users.user_id AS student_id,
            users.name AS student_name
        FROM issues
        JOIN locations ON locations.location_id = issues.location_id
        LEFT JOIN users ON users.user_id = issues.user_id
        {where_clause}
        ORDER BY issues.created_at DESC, issues.issue_id DESC
        LIMIT ? OFFSET ?
        """,
        [*parameters, per_page, (page - 1) * per_page],
    )
    locations = query_db(
        """
        SELECT location_id, building_name, area_name
        FROM locations
        ORDER BY building_name, area_name
        """
    )
    trend_counts = {
        row["day"]: row["count"]
        for row in query_db(
            """
            SELECT date(created_at) AS day, COUNT(*) AS count
            FROM issues
            WHERE date(created_at) >= date('now', '-13 days')
            GROUP BY date(created_at)
            """
        )
    }
    today = date.today()
    trend = [
        {
            "day": (today - timedelta(days=days_ago)).isoformat(),
            "count": trend_counts.get((today - timedelta(days=days_ago)).isoformat(), 0),
        }
        for days_ago in range(13, -1, -1)
    ]

    return jsonify({
        "data": {"issues": [dict(issue) for issue in issues]},
        "meta": {
            "page": page,
            "per_page": per_page,
            "count": len(issues),
            "total": filtered_total,
            "pages": pages,
            "summary": dict(summary),
            "trend": trend,
            "filters": {
                "categories": list(ISSUE_CATEGORIES),
                "locations": [dict(location) for location in locations],
                "statuses": list(REPORT_STATUS_FILTERS),
                "priorities": sorted(ADMIN_PRIORITIES),
            },
        },
    })


    query = """
        SELECT
            issues.*,
            locations.building_name,
            locations.area_name,
            locations.floor_number,
            assignee.name AS assigned_name
        FROM issues
        JOIN locations ON locations.location_id = issues.location_id
        LEFT JOIN users AS assignee ON assignee.user_id = issues.assigned_to
        WHERE issues.issue_id = ?
    """
    parameters = [issue_id]
    if user["role"] == "student":
        query += " AND issues.user_id = ?"
        parameters.append(user["user_id"])
    return query_db(query, parameters, one=True)


def serialize_issue(issue):
    return {
        "issue_id": issue["issue_id"],
        "title": issue["title"],
        "description": issue["description"],
        "category": issue["category"],
        "priority": issue["priority"],
        "status": issue["status"],
        "created_at": issue["created_at"],
        "photo_path": issue["photo_path"],
        "photo_url": url_for("issue_photo", issue_id=issue["issue_id"]) if issue["photo_path"] else None,
        "location": {
            "building_name": issue["building_name"],
            "area_name": issue["area_name"],
            "floor_number": issue["floor_number"],
        },
    }


@app.route("/api/my-reports")
@app.route("/api/reports")
@login_required
@roles_required("student", "admin")
def my_reports_api():
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    search = request.args.get("q", "").strip()

    if category and category not in ISSUE_CATEGORIES:
        return api_error("invalid_category", "Choose a valid issue category.", 400)
    if status and status not in REPORT_STATUS_FILTERS:
        return api_error("invalid_status", "Choose a valid report status filter.", 400)
    if len(search) > 120:
        return api_error("search_too_long", "Search text must be 120 characters or fewer.", 400)

    base_conditions = []
    base_parameters = []
    if g.current_user["role"] == "student":
        base_conditions.append("issues.user_id = ?")
        base_parameters.append(g.current_user["user_id"])
    base_where = f"WHERE {' AND '.join(base_conditions)}" if base_conditions else ""

    summary = query_db(
        f"""
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN status IN ('submitted', 'under_review') THEN 1 ELSE 0 END), 0) AS pending,
            COALESCE(SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END), 0) AS in_progress,
            COALESCE(SUM(CASE WHEN status IN ('resolved', 'closed') THEN 1 ELSE 0 END), 0) AS resolved
        FROM issues
        {base_where}
        """,
        base_parameters,
        one=True,
    )
    trend_where = (
        f"{base_where} AND date(created_at) >= date('now', '-13 days')"
        if base_where
        else "WHERE date(created_at) >= date('now', '-13 days')"
    )
    trend_counts = {
        row["day"]: row["count"]
        for row in query_db(
            f"""
            SELECT date(created_at) AS day, COUNT(*) AS count
            FROM issues
            {trend_where}
            GROUP BY date(created_at)
            """,
            base_parameters,
        )
    }
    today = date.today()
    trend = [
        {
            "day": (today - timedelta(days=days_ago)).isoformat(),
            "count": trend_counts.get((today - timedelta(days=days_ago)).isoformat(), 0),
        }
        for days_ago in range(13, -1, -1)
    ]

    conditions = list(base_conditions)
    parameters = list(base_parameters)
    if category:
        conditions.append("issues.category = ?")
        parameters.append(category)
    if status:
        status_values = REPORT_STATUS_FILTERS[status]
        placeholders = ", ".join("?" for _ in status_values)
        conditions.append(f"issues.status IN ({placeholders})")
        parameters.extend(status_values)
    if search:
        search_conditions = [
            "instr(CAST(issues.issue_id AS TEXT), ?) > 0",
            "instr(lower(issues.title), lower(?)) > 0",
            "instr(lower(issues.description), lower(?)) > 0",
            "instr(lower(issues.category), lower(?)) > 0",
            "instr(lower(locations.building_name), lower(?)) > 0",
            "instr(lower(locations.area_name), lower(?)) > 0",
        ]
        conditions.append(f"({' OR '.join(search_conditions)})")
        parameters.extend([search] * len(search_conditions))
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    reports = query_db(
        f"""
        SELECT
            issues.issue_id,
            issues.title,
            issues.description,
            issues.category,
            issues.priority,
            issues.status,
            issues.created_at,
            issues.photo_path,
            locations.building_name,
            locations.area_name,
            locations.floor_number
        FROM issues
        JOIN locations ON locations.location_id = issues.location_id
        {where_clause}
        ORDER BY issues.created_at DESC, issues.issue_id DESC
        """,
        parameters,
    )
    return jsonify({
        "data": {"reports": [serialize_issue(report) for report in reports]},
        "meta": {
            "count": len(reports),
            "total": summary["total"],
            "summary": dict(summary),
            "trend": trend,
        },
    })


@app.route("/api/issues/<int:issue_id>")
@login_required
@roles_required("student", "admin")
def issue_details_api(issue_id):
    issue = issue_for_user(issue_id, g.current_user)
    if issue is None:
        return api_error("not_found", "Report not found.", 404)
    return jsonify({"data": {"issue": serialize_issue(issue)}})


@app.route("/api/issues/<int:issue_id>/history")
@login_required
@roles_required("student", "admin")
def issue_history_api(issue_id):
    issue = issue_for_user(issue_id, g.current_user)
    if issue is None:
        return api_error("not_found", "Report not found.", 404)

    history = query_db(
        """
        SELECT
            issue_history.history_id,
            issue_history.issue_id,
            issue_history.old_status,
            issue_history.new_status,
            issue_history.event_type,
            issue_history.old_assigned_to,
            issue_history.new_assigned_to,
            issue_history.updated_by,
            issue_history.updated_at,
            issue_history.comment,
            actor.name AS updated_by_name,
            old_assignee.name AS old_assignee_name,
            new_assignee.name AS new_assignee_name
        FROM issue_history
        LEFT JOIN users AS actor ON actor.user_id = issue_history.updated_by
        LEFT JOIN users AS old_assignee ON old_assignee.user_id = issue_history.old_assigned_to
        LEFT JOIN users AS new_assignee ON new_assignee.user_id = issue_history.new_assigned_to
        WHERE issue_history.issue_id = ?
                        "total": summary["total"],
                        "summary": dict(summary),
        """,
        (issue_id,),
    )
    return jsonify({
        "data": {"history": [dict(update) for update in history]},
        "meta": {"count": len(history)},
    })


@app.route("/issues/<int:issue_id>")
@login_required
@roles_required("student", "admin")
def issue_detail(issue_id):
    issue = issue_for_user(issue_id, g.current_user)
    if issue is None:
        abort(404)

    history = query_db(
        """
        SELECT
            issue_history.*,
            actor.name AS updated_by_name,
            old_assignee.name AS old_assignee_name,
            new_assignee.name AS new_assignee_name
        FROM issue_history
        LEFT JOIN users AS actor ON actor.user_id = issue_history.updated_by
        LEFT JOIN users AS old_assignee ON old_assignee.user_id = issue_history.old_assigned_to
        LEFT JOIN users AS new_assignee ON new_assignee.user_id = issue_history.new_assigned_to
        WHERE issue_history.issue_id = ?
        ORDER BY issue_history.updated_at ASC, issue_history.history_id ASC
        """,
        (issue_id,),
    )
    assignees = query_db(
        """
        SELECT user_id, name, email, role
        FROM users
        WHERE role IN (?, ?)
        ORDER BY role, name
        """,
        ("maintenance", "admin"),
    )
    return render_template(
        "issue_details.html",
        issue=issue,
        history=history,
        assignees=assignees,
        status_labels={
            "submitted": "Pending",
            "under_review": "Pending",
            "in_progress": "In Progress",
            "resolved": "Resolved",
            "closed": "Resolved",
        },
    )


@app.route("/issues/<int:issue_id>/photo")
@login_required
@roles_required("student", "admin")
def issue_photo(issue_id):
    issue = issue_for_user(issue_id, g.current_user)
    if issue is None or not issue["photo_path"]:
        abort(404)

    stored_path = issue["photo_path"]
    parts = Path(stored_path).parts
    if len(parts) != 2 or parts[0] != "uploads" or "\\" in stored_path:
        abort(404)
    filename = parts[1]
    extension = Path(filename).suffix.lower()
    if Path(filename).name != filename or extension not in ALLOWED_PHOTO_EXTENSIONS:
        abort(404)

    upload_directory = Path(app.config["UPLOAD_FOLDER"]).resolve()
    photo_path = (upload_directory / filename).resolve()
    try:
        photo_path.relative_to(upload_directory)
    except ValueError:
        abort(404)
    if not photo_path.is_file():
        abort(404)

    image_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    response = send_file(photo_path, mimetype=image_types[extension], conditional=True, max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.route("/api/issues/<int:issue_id>", methods=["PATCH"])
@login_required
@roles_required("admin")
def update_issue(issue_id):
    issue = query_db(
        "SELECT issue_id, status, priority, assigned_to FROM issues WHERE issue_id = ?",
        (issue_id,),
        one=True,
    )
    if issue is None:
        return api_error("not_found", "Report not found.", 404)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error("invalid_payload", "Send a JSON object with the fields to update.", 400)
    supported_fields = {"status", "assigned_to", "priority", "comment"}
    if payload.keys() - supported_fields:
        return api_error("unsupported_fields", "The request includes unsupported fields.", 400)
    if not payload.keys() & {"status", "assigned_to", "priority"}:
        return api_error("no_updates", "Provide a status, assignee, or priority update.", 400)

    comment = payload.get("comment", "")
    if not isinstance(comment, str):
        return api_error("invalid_comment", "The comment must be text.", 400)
    comment = comment.strip()
    if len(comment) > 500:
        return api_error("invalid_comment", "Comments must be 500 characters or fewer.", 400)

    old_status = issue["status"]
    old_assignment = issue["assigned_to"]
    new_status = old_status
    status_changed = False
    if "status" in payload:
        requested_status = payload["status"]
        if not isinstance(requested_status, str) or requested_status not in ADMIN_STATUS_TRANSITIONS:
            return api_error("invalid_status", "Choose Pending, In Progress, or Resolved.", 400)
        current_group = (
            "pending" if old_status in {"submitted", "under_review"}
            else "in_progress" if old_status == "in_progress"
            else "resolved"
        )
        if requested_status not in ADMIN_STATUS_TRANSITIONS[current_group]:
            return api_error(
                "invalid_status_transition",
                f"A report cannot move from {current_group.replace('_', ' ')} to {requested_status.replace('_', ' ')}.",
                400,
            )
        if requested_status == "resolved" and current_group != "resolved" and not comment:
            return api_error("resolution_comment_required", "Add a comment when resolving a report.", 400)
        new_status = (
            old_status
            if requested_status == "pending" and old_status in {"submitted", "under_review"}
            else "submitted" if requested_status == "pending"
            else requested_status
        )
        status_changed = new_status != old_status

    new_assignment = old_assignment
    assignment_changed = False
    if "assigned_to" in payload:
        requested_assignee = payload["assigned_to"]
        if requested_assignee in (None, ""):
            new_assignment = None
        else:
            if isinstance(requested_assignee, bool) or not isinstance(requested_assignee, (int, str)):
                return api_error("invalid_assignee", "Choose a maintenance staff member or administrator.", 400)
            if isinstance(requested_assignee, str) and not requested_assignee.isdecimal():
                return api_error("invalid_assignee", "Choose a maintenance staff member or administrator.", 400)
            try:
                new_assignment = int(requested_assignee)
            except (TypeError, ValueError):
                return api_error("invalid_assignee", "Choose a maintenance staff member or administrator.", 400)
            assignee = query_db(
                "SELECT user_id FROM users WHERE user_id = ? AND role IN (?, ?)",
                (new_assignment, "maintenance", "admin"),
                one=True,
            )
            if assignee is None:
                return api_error("invalid_assignee", "Only maintenance staff and administrators can be assigned.", 400)
        assignment_changed = new_assignment != old_assignment

    new_priority = issue["priority"]
    priority_changed = False
    if "priority" in payload:
        requested_priority = payload["priority"]
        if not isinstance(requested_priority, str) or requested_priority not in ADMIN_PRIORITIES:
            return api_error("invalid_priority", "Choose Low, Normal, High, or Critical.", 400)
        new_priority = requested_priority
        priority_changed = new_priority != issue["priority"]

    if not (status_changed or assignment_changed or priority_changed or comment):
        return api_error("no_changes", "The issue already has these values.", 400)

    db = get_db()
    db.execute(
        "UPDATE issues SET status = ?, assigned_to = ?, priority = ? WHERE issue_id = ?",
        (new_status, new_assignment, new_priority, issue_id),
    )
    actor_id = g.current_user["user_id"]
    if status_changed or (comment and "status" in payload):
        db.execute(
            """
            INSERT INTO issue_history (
                issue_id, old_status, new_status, event_type, updated_by, comment
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (issue_id, old_status, new_status, "status", actor_id, comment or None),
        )
    if assignment_changed:
        db.execute(
            """
            INSERT INTO issue_history (
                issue_id, old_status, new_status, event_type,
                old_assigned_to, new_assigned_to, updated_by, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue_id,
                new_status,
                new_status,
                "assignment",
                old_assignment,
                new_assignment,
                actor_id,
                comment or None if not status_changed else None,
            ),
        )
    db.commit()

    return jsonify({
        "data": {
            "issue_id": issue_id,
            "status": "pending" if new_status in {"submitted", "under_review"} else "resolved" if new_status == "closed" else new_status,
            "priority": new_priority,
            "assigned_to": new_assignment,
            "changes": {
                "status": status_changed,
                "assignment": assignment_changed,
                "priority": priority_changed,
            },
        }
    })


@app.route("/report", methods=["GET", "POST"])
@login_required
@roles_required("student")
def report_issue():
    locations = query_db(
        """
        SELECT location_id, building_name, area_name, floor_number
        FROM locations
        ORDER BY building_name, floor_number, area_name
        """
    )
    form_data = {}
    field_errors = {}

    if request.method == "POST":
        form_data = {
            "title": request.form.get("title", "").strip(),
            "description": request.form.get("description", "").strip(),
            "category": request.form.get("category", "").strip(),
            "location_id": request.form.get("location_id", "").strip(),
        }

        if not form_data["title"]:
            field_errors["title"] = "Enter a short title for the issue."
        elif len(form_data["title"]) > 120:
            field_errors["title"] = "Keep the title to 120 characters or fewer."

        if not form_data["description"]:
            field_errors["description"] = "Describe what needs attention."
        elif len(form_data["description"]) > 2000:
            field_errors["description"] = "Keep the description to 2,000 characters or fewer."

        if form_data["category"] not in ISSUE_CATEGORIES:
            field_errors["category"] = "Choose a category from the list."

        try:
            location_id = int(form_data["location_id"])
        except ValueError:
            location_id = None
        location = query_db(
            """
            SELECT location_id FROM locations WHERE location_id = ?
            """,
            (location_id,),
            one=True,
        ) if location_id is not None else None
        if location is None:
            field_errors["location_id"] = "Choose a valid campus location."

        photo = request.files.get("photo")
        photo_content = None
        photo_extension = None
        if photo and photo.filename:
            photo_extension = Path(photo.filename).suffix.lower()
            if photo_extension not in ALLOWED_PHOTO_EXTENSIONS:
                field_errors["photo"] = "Choose a JPEG, PNG, or WebP image."
            else:
                photo_content = photo.stream.read(MAX_PHOTO_SIZE + 1)
                if len(photo_content) > MAX_PHOTO_SIZE:
                    field_errors["photo"] = "The image must be 5 MB or smaller."
                elif not PHOTO_SIGNATURES[photo_extension](photo_content):
                    field_errors["photo"] = "The selected file does not match its image type."
                else:
                    try:
                        photo_content = sanitize_uploaded_image(photo_content, photo_extension)
                    except UploadValidationError as error:
                        field_errors["photo"] = str(error)

        if field_errors:
            return render_template(
                "report_issue.html",
                categories=ISSUE_CATEGORIES,
                locations=locations,
                form_data=form_data,
                field_errors=field_errors,
            ), 400

        duplicate_issue = None
        if request.form.get("submit_anyway") != "1":
            candidates = query_db(
                """
                SELECT issue_id, title, status, created_at
                FROM issues
                WHERE location_id = ?
                  AND category = ?
                  AND status NOT IN ('resolved', 'closed')
                  AND created_at >= datetime('now', '-7 days')
                ORDER BY created_at DESC, issue_id DESC
                """,
                (location_id, form_data["category"]),
            )

            def normalized_title(value):
                return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

            submitted_title = normalized_title(form_data["title"])
            likely_matches = [
                (difflib.SequenceMatcher(
                    None, submitted_title, normalized_title(candidate["title"]), autojunk=False
                ).ratio(), candidate)
                for candidate in candidates
            ]
            likely_matches = [match for match in likely_matches if match[0] >= 0.78]
            if likely_matches:
                duplicate_issue = max(likely_matches, key=lambda match: (match[0], match[1]["created_at"]))[1]

        if duplicate_issue is not None:
            return render_template(
                "report_issue.html",
                categories=ISSUE_CATEGORIES,
                locations=locations,
                form_data=form_data,
                field_errors={},
                duplicate_issue=duplicate_issue,
            )

        photo_path = None
        saved_photo = None
        try:
            if photo_content is not None:
                upload_directory = Path(app.config["UPLOAD_FOLDER"]).resolve()
                upload_directory.mkdir(parents=True, exist_ok=True)
                filename = f"{uuid.uuid4().hex}{photo_extension}"
                saved_photo = (upload_directory / filename).resolve()
                saved_photo.relative_to(upload_directory)
                with saved_photo.open("wb") as uploaded_file:
                    uploaded_file.write(photo_content)
                photo_path = f"uploads/{filename}"

            create_issue(
                user_id=g.current_user["user_id"],
                title=form_data["title"],
                description=form_data["description"],
                category=form_data["category"],
                location_id=location_id,
                photo_path=photo_path,
            )
        except Exception:
            if saved_photo:
                saved_photo.unlink(missing_ok=True)
            raise

        return redirect(url_for("report_issue", submitted="1"))

    return render_template(
        "report_issue.html",
        categories=ISSUE_CATEGORIES,
        locations=locations,
        form_data=form_data,
        field_errors=field_errors,
    )


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(error):
    if request.endpoint != "report_issue":
        return "Request is too large.", 413
    locations = query_db(
        """
        SELECT location_id, building_name, area_name, floor_number
        FROM locations
        ORDER BY building_name, floor_number, area_name
        """
    )
    return render_template(
        "report_issue.html",
        categories=ISSUE_CATEGORIES,
        locations=locations,
        form_data={},
        field_errors={"photo": "The upload is too large. Images must be 5 MB or smaller."},
    ), 413


with app.app_context():
    migrate_legacy_uploaded_photos()


if __name__ == "__main__":
    app.run()
