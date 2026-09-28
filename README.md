# Fix My Campus

A college campus issue-reporting project built by Team Nexora with Python, Flask, SQLite, HTML, CSS, and vanilla JavaScript.

Students can report campus issues, follow their status, and review update history. Administrators can search and manage all reports. Maintenance accounts can be assigned to issues.

## Requirements

- Python 3.12 or newer
- pip

## Set Up Locally

From the project folder, create and activate a virtual environment, then install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Set a session secret before starting the app. Generate a new value for your own environment; do not commit it to the project:

```bash
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

Optionally restrict registration to your college's email domain:

```bash
export COLLEGE_EMAIL_DOMAIN="your-college.edu"
```

Start the development server:

```bash
flask --app app run --debug --port 5003
```

Open <http://127.0.0.1:5003> in your browser. If port 5003 is already in use, choose another port with `--port`.

Flask creates the `instance/` directory and initializes `instance/campus.db` automatically. Existing database records are preserved during initialization and schema upgrades.

## Accounts

Create the first administrator with the interactive Flask CLI command. It prompts for the account name, college email, and password without putting the password in shell history:

```bash
flask --app app create-admin
```

Create an assignable maintenance account the same way:

```bash
flask --app app create-maintenance
```

Public registration always creates a student account. It collects a name, email, and password; passwords must be at least 12 characters and include a letter and a number. If `COLLEGE_EMAIL_DOMAIN` is set, registration is restricted to that exact domain.

Sign-in and registration are available at `/login` and `/register`. Signing out uses a CSRF-protected POST request. Session cookies are HttpOnly and SameSite=Lax. For HTTPS deployments, set `FLASK_COOKIE_SECURE=1`; leave it unset for local HTTP development. Set a stable `FLASK_SECRET_KEY` in the server environment so sessions remain valid across restarts.

## Main Routes

| Route                      | Purpose                                           | Access                                          |
| -------------------------- | ------------------------------------------------- | ----------------------------------------------- |
| `/`                        | Public homepage                                   | Public                                          |
| `/register`                | Create a student account                          | Public                                          |
| `/login`                   | Sign in                                           | Public                                          |
| `/logout`                  | Sign out                                          | Signed-in user, POST with CSRF token            |
| `/report`                  | Submit an issue with an optional photo            | Student                                         |
| `/my-reports`              | View and filter submitted reports                 | Student or admin                                |
| `/issues/<id>`             | View issue details and status history             | Owner student or admin                          |
| `/admin`                   | Admin dashboard                                   | Admin                                           |
| `/admin/analytics`         | Campus issue analytics and date-filtered charts   | Admin                                           |
| `/admin/map`               | Campus location map and report list               | Admin                                           |
| `/api/my-reports`          | List the current user's reports                   | Student or admin                                |
| `/api/reports`             | Search/filter reports                             | Student or admin                                |
| `/api/admin/issues`        | Filtered, paginated issue list and summary counts | Admin                                           |
| `/api/admin/analytics`     | Date-filtered metrics, charts, and unresolved hotspots | Admin                                      |
| `/api/admin/map`           | Filtered campus location counts and report summaries | Admin                                       |
| `/api/issues/<id>`         | Get issue details; admins can update with PATCH   | Owner student or admin for GET; admin for PATCH |
| `/api/issues/<id>/history` | Get issue status and assignment history           | Owner student or admin                          |

Admin issue filters include `q`, `status`, `category`, `location`, and `priority`; pagination uses `page` and `per_page`. The PATCH endpoint accepts JSON fields `status`, `assigned_to`, `priority`, and `comment`. Resolving an issue requires a comment. Valid priorities are `low`, `normal`, `high`, and `critical`.

The admin analytics page reports total and unresolved issues, resolution rate, average resolution time, issue counts by category and location, monthly submission trends, and locations with the most unresolved reports. An optional start and end date filters reports by their submission date. Resolution time uses the issue creation timestamp and the first resolved or closed status timestamp recorded in issue history. Charts use Chart.js loaded from jsDelivr.

The admin issue map uses Leaflet and OpenStreetMap tiles. It is centered on the provided approximate campus coordinate (26.7759, 75.8745). Configure verified per-location coordinates in the `CAMPUS_LOCATION_COORDINATES` environment variable as a JSON object whose keys are `Building Name|Area Name` and whose values are `[latitude, longitude]`. Configure the actual coordinates for each location already listed in the `locations` table; until then, its report list remains available but it has no individual map marker. The map does not use browser geolocation or expose reporter identity or personal location data. OpenStreetMap tile use requires visible attribution and must follow the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

## Issue Photos

The report form accepts JPEG, PNG, and WebP images up to 5 MB. The server checks both the file extension and image signature, assigns a generated filename, and stores uploads under `static/uploads/`. Original client filenames are not used as disk paths.

## Duplicate Report Warning

When a student submits a report, the app checks unresolved reports from the previous seven days at the same location and in the same category. It lowercases titles, removes punctuation, and compares them with Python's `difflib.SequenceMatcher`; a similarity score of 0.78 or higher displays the closest match for review. Students can cancel or submit their report anyway. The warning never merges or deletes reports. This title-only heuristic can miss differently worded reports about the same problem and can flag similar titles about separate problems. If the warning is shown, an attached photo must be selected again before choosing to submit anyway.

## Project Structure

```text
FixMyCampus/
|-- app.py                     Flask routes, authentication, authorization, and CLI commands
|-- database.py                SQLite schema, initialization, migrations, and query helpers
|-- requirements.txt           Python dependencies
|-- instance/
|   |-- campus.db              Automatically created SQLite database
|-- templates/
|   |-- index.html             Public homepage
|   |-- login.html             Sign-in form
|   |-- register.html          Student registration form
|   |-- report_issue.html      New issue form
|   |-- my_reports.html        Student report portal
|   |-- issue_details.html     Issue details and history
|   |-- admin_dashboard.html   Admin dashboard
|   |-- admin_analytics.html  Admin issue analytics
|   `-- admin_map.html        Admin campus map and accessible report list
`-- static/
|-- css/                   Page stylesheets
|-- js/                    Vanilla JavaScript, Chart.js, and Leaflet interactions
`-- uploads/               Uploaded issue photos
```

## Notes

- SQLite connections enable foreign-key enforcement.
- Form POST requests and admin PATCH requests are CSRF-protected.
- Students can only view their own reports. Admin report access and management are role-protected.
- Keep `.venv/`, secrets, and the generated database out of version control. The repository `.gitignore` already excludes the virtual environment and local database.
- Email verification and password reset are not currently implemented.
# FixMyCampus
