# Fix My Campus

Fix My Campus is a Flask web application for reporting and tracking campus maintenance issues. Students can submit reports and follow their own reports. Administrators can review reports, update their status and priority, assign maintenance staff, view campus analytics, and browse reports by campus location.

The application uses Python, Flask, SQLite, Jinja templates, and browser JavaScript. It is intended for local development and classroom or campus project use. The Flask development server is not a production deployment server.

## Features

- Public home, registration, and login pages.
- Student registration creates student accounts only. Admin and maintenance accounts are created through Flask CLI commands.
- Issue reports with title, description, category, predefined building/area, and optional image.
- Student report list, category/status filters, report details, and status history. Students can only access their own reports.
- Admin dashboard with search, filters, pagination, report assignment, priority changes, and status updates. Resolving a report requires an admin comment.
- Admin analytics for totals, unresolved issues, resolution rate, average resolution time, issue counts by category/location, monthly report trends, and unresolved hotspots. Analytics can be filtered by report submission dates.
- Admin campus map with category and status filters, unresolved report counts, report popups, and an accessible location/report list.
- A duplicate report warning for unresolved issues at the same location/category reported within seven days. Students choose whether to continue; reports are never automatically merged or deleted.
- CSRF protection for form submissions and admin API updates, signed sessions, and role-based route access.

## Architecture

- `app.py` defines Flask pages, JSON APIs, authentication, authorization, upload validation, and account CLI commands.
- `database.py` defines SQLite access, schema initialization, migrations, and issue creation/history helpers.
- SQLite is the only application database. The normal local database is `instance/campus.db`; SQLite tables are created on application startup.
- Jinja templates render pages and expose Flask-generated API URLs through `data-*` attributes. Page JavaScript reads those URLs instead of hardcoding application hostnames.
- CSS and browser JavaScript are served from `static/`.
- Chart.js and Leaflet are loaded from public CDNs. Leaflet map tiles come from OpenStreetMap.

## Requirements

- Python 3.12 or newer
- `pip`
- Internet access in the browser for Chart.js, Leaflet, and OpenStreetMap map tiles

## Fresh Local Installation

Run these commands from the repository directory.

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   On Windows PowerShell, activate it with `.venv\Scripts\Activate.ps1`.

2. Install application dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Set a stable secret key for signed sessions. Generate your own value and keep it out of source control:

   ```bash
   export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
   ```

   If `FLASK_SECRET_KEY` is omitted, the application generates a temporary key at startup. Sessions will not survive an application restart in that case.

4. Optionally limit new registrations to a college email domain:

   ```bash
   export COLLEGE_EMAIL_DOMAIN="your-college.edu"
   ```

   Omit this setting to allow any syntactically valid email domain.

5. Start Flask:

   ```bash
   flask --app app run --debug --port 5003
   ```

6. Open <http://127.0.0.1:5003>.

The first application startup creates `instance/`, initializes `instance/campus.db`, creates the schema, and inserts the predefined starter locations if they are missing. The schema initializer includes migrations for earlier database layouts. Back up your database and uploads before upgrading. Uploaded images are stored in the private `instance/uploads/` directory.

For local development, leave `FLASK_COOKIE_SECURE` unset. For HTTPS deployments set it to `1` so browsers send the session cookie only over HTTPS. Do not use Flask's debug server for public production hosting.

## Accounts and Roles

Create the first administrator from an activated virtual environment:

```bash
flask --app app create-admin
```

The command interactively requests the name, email, and password; the password is hidden while typing. It refuses to create another admin when an admin account already exists.

Create a maintenance account that can be assigned to a report:

```bash
flask --app app create-maintenance
```

Students register at `/register`. Passwords must contain at least 12 characters, a letter, and a number. Public registration cannot select or create privileged roles. Sign in at `/login`; logout is a CSRF-protected POST action.

| Role | Access |
| --- | --- |
| Public | Homepage, registration, login |
| Student | Submit reports; list, view, and track their own reports |
| Maintenance | Sign in; can be assigned to reports. No maintenance-specific dashboard is implemented. |
| Admin | Dashboard, all reports, issue updates, analytics, and campus map |

## Pages and APIs

| Page or endpoint | Purpose | Access |
| --- | --- | --- |
| `/` | Homepage | Public |
| `/register`, `/login` | Account registration and sign in | Public |
| `/logout` | Sign out; POST with CSRF token | Signed-in user |
| `/report` | Submit a report and optional photo | Student |
| `/my-reports` | Report portal | Student or admin |
| `/issues/<id>` | Report details and history | Owner student or admin |
| `/issues/<id>/photo` | Private report photo | Owner student or admin |
| `/admin` | Admin issue dashboard | Admin |
| `/admin/analytics` | Analytics page | Admin |
| `/admin/map` | Campus map and location list | Admin |
| `/api/my-reports` and `/api/reports` | List/search the current user's reports; admins see all reports | Student or admin |
| `/api/issues/<id>` | Read a report; admin PATCH updates status, assignee, priority, and comment | Owner student/admin for GET; admin for PATCH |
| `/api/issues/<id>/history` | Read report status and assignment history | Owner student or admin |
| `/api/admin/issues` | Filtered and paginated admin report data | Admin |
| `/api/admin/analytics` | Date-filtered metrics and chart/hotspot data | Admin |
| `/api/admin/map` | Filtered location counts and report summaries | Admin |

Admin issue filters are `q`, `status`, `category`, `location`, and `priority`; pagination uses `page` and `per_page`. Status changes follow the application's allowed transitions. Resolutions require a comment. Priorities are `low`, `normal`, `high`, and `critical`.

Analytics accept optional `start_date` and `end_date` in `YYYY-MM-DD` format, based on report creation dates. Average resolution time is calculated from the issue creation time to its first `resolved` or `closed` status-history timestamp. Reports without a resolution history do not contribute to that average.

## Campus Map Coordinates

The map uses the approximate campus-center coordinate `(26.7759, 75.8745)` for its initial view. That point is **not** assigned to individual buildings. No individual marker appears until verified coordinates are configured for that exact location.

Set `CAMPUS_LOCATION_COORDINATES` to a JSON object. Each key must exactly match a database location in the form `Building Name|Area Name`; each value is `[latitude, longitude]`:

```bash
export CAMPUS_LOCATION_COORDINATES='{"Building Name|Area Name":[LATITUDE,LONGITUDE]}'
```

Replace the example key and coordinate values with verified values for each location. Do not put the campus-center point under every building. The app does not request student geolocation or include reporter names/emails in map responses. The location/report list still works when coordinates are absent. OpenStreetMap attribution is displayed; use of its public tile service is subject to the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

## Issue Photos

The report form accepts JPEG, PNG, and WebP files up to 5 MB. The server checks the extension, file signature, decoded format, dimensions, and frame count, then re-encodes the image and assigns a random filename. Files are kept under `instance/uploads/`, outside Flask's public static directory. The photo route checks report ownership before returning a file. The original client filename is not used as a storage path.

At startup, the app attempts to move referenced legacy files from `static/uploads/` into private storage. Invalid or missing legacy images are skipped; back up an existing database and uploads before upgrading a deployed copy.

## Duplicate Report Warning

Before saving a report, the app checks unresolved reports from the last seven days at the same location and in the same category. It lowercases titles, removes punctuation, and compares them with `difflib.SequenceMatcher`; a score of 0.78 or higher can trigger a warning. A student can cancel or submit anyway. The heuristic can miss different descriptions of the same issue and flag similar titles about separate issues. If the warning appears, the browser requires the student to select the photo again before resubmitting.

## Database Tables

- `users`: student, maintenance, and admin accounts with password hashes and roles.
- `locations`: predefined building, area, and floor records used by report forms and the map.
- `issues`: report text, category, location, status, priority, assignee, timestamp, and private photo path.
- `issue_history`: initial submission, status changes, comments, and assignment changes.

SQLite connections enable foreign-key checks. The schema initializer creates tables and indexes and includes migrations for older application schemas. You can direct the app to a separate database or upload folder with `FIX_MY_CAMPUS_DATABASE` and `FIX_MY_CAMPUS_UPLOAD_FOLDER`; tests use these settings to isolate startup and request data from the development database.

## Project Structure

```text
FixMyCampus/
├── app.py                    Flask app, routes, security, uploads, CLI commands
├── database.py               SQLite schema, migrations, and query helpers
├── requirements.txt          Runtime dependencies
├── requirements-dev.txt      Runtime dependencies plus pytest
├── README.md                 Setup, feature, and limitation documentation
├── tests/
│   ├── conftest.py           Isolated temporary database and test fixtures
│   └── test_app.py           Flask route, database, auth, upload, and analytics tests
├── instance/                 Created on startup; local database and private uploads
├── templates/                Jinja pages for public, student, and admin views
└── static/
    ├── css/                  Page stylesheets
    └── js/                   Page interactions and API clients
```

## Tests

Install development dependencies and run the tests:

```bash
python -m pip install -r requirements-dev.txt
pytest
```

Tests point app startup and each test fixture at temporary SQLite databases and upload directories. They do not modify `instance/campus.db` or the regular upload directory.

## Known Limitations

- Email verification and password reset are not implemented.
- Maintenance accounts can be assigned but have no dedicated dashboard.
- Duplicate detection is a title similarity heuristic, not semantic matching.
- The starter location names are generic project data; verify or replace them for your campus.
- Individual map markers require verified coordinates. The supplied campus center is only an initial map view.
- Chart.js, Leaflet, and OpenStreetMap tiles require an internet connection in the browser.
- The Flask built-in server and debug mode are for local development only.
