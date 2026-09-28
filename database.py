import sqlite3

from flask import current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    email TEXT NOT NULL COLLATE NOCASE UNIQUE
        CHECK (length(trim(email)) > 0),
    password_hash TEXT NOT NULL CHECK (length(password_hash) > 0),
    role TEXT NOT NULL CHECK (role IN ('student', 'maintenance', 'admin'))
);

CREATE TABLE IF NOT EXISTS locations (
    location_id INTEGER PRIMARY KEY AUTOINCREMENT,
    building_name TEXT NOT NULL CHECK (length(trim(building_name)) > 0),
    area_name TEXT NOT NULL CHECK (length(trim(area_name)) > 0),
    floor_number INTEGER NOT NULL,
    UNIQUE (building_name, area_name, floor_number)
);

CREATE TABLE IF NOT EXISTS issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    category TEXT NOT NULL CHECK (length(trim(category)) > 0),
    location_id INTEGER NOT NULL,
    photo_path TEXT,
    priority TEXT NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted', 'under_review', 'in_progress', 'resolved', 'closed')),
    assigned_to INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
    FOREIGN KEY (location_id) REFERENCES locations (location_id) ON DELETE RESTRICT,
    FOREIGN KEY (assigned_to) REFERENCES users (user_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS issue_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL,
    old_status TEXT CHECK (
        old_status IS NULL OR old_status IN ('submitted', 'under_review', 'in_progress', 'resolved', 'closed')
    ),
    new_status TEXT NOT NULL
        CHECK (new_status IN ('submitted', 'under_review', 'in_progress', 'resolved', 'closed')),
    event_type TEXT NOT NULL DEFAULT 'status'
        CHECK (event_type IN ('status', 'assignment')),
    old_assigned_to INTEGER,
    new_assigned_to INTEGER,
    updated_by INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    comment TEXT,
    FOREIGN KEY (issue_id) REFERENCES issues (issue_id) ON DELETE CASCADE,
    FOREIGN KEY (updated_by) REFERENCES users (user_id) ON DELETE SET NULL,
    FOREIGN KEY (old_assigned_to) REFERENCES users (user_id) ON DELETE SET NULL,
    FOREIGN KEY (new_assigned_to) REFERENCES users (user_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_issues_user_id ON issues (user_id);
CREATE INDEX IF NOT EXISTS idx_issues_location_id ON issues (location_id);
CREATE INDEX IF NOT EXISTS idx_issues_assigned_to ON issues (assigned_to);
CREATE INDEX IF NOT EXISTS idx_issues_status ON issues (status);
CREATE INDEX IF NOT EXISTS idx_issues_category ON issues (category);
CREATE INDEX IF NOT EXISTS idx_issues_created_at ON issues (created_at);
CREATE INDEX IF NOT EXISTS idx_issue_history_issue_id ON issue_history (issue_id);
CREATE INDEX IF NOT EXISTS idx_issue_history_updated_by ON issue_history (updated_by);
"""

STARTER_LOCATIONS = (
    ("Main Academic Building", "Main Entrance", 1),
    ("Main Academic Building", "Computer Lab", 2),
    ("Library", "Ground-Floor Reading Room", 0),
    ("Student Center", "Cafeteria", 1),
    ("Science Building", "Chemistry Laboratory", 2),
)


def get_db():
    """Return this request's SQLite connection, creating it when needed."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def query_db(query, parameters=(), one=False):
    """Run a parameterized query and return one row or all matching rows."""
    cursor = get_db().execute(query, parameters)
    rows = cursor.fetchall()
    return (rows[0] if rows else None) if one else rows


def init_db():
    """Create missing tables and indexes, then add any missing starter locations."""
    db = get_db()
    db.executescript(SCHEMA)
    _make_issue_reporter_optional(db)
    _normalize_issue_priority(db)
    _restrict_user_roles(db)
    _add_issue_history_assignment_fields(db)
    db.executescript(SCHEMA)
    db.executemany(
        """
        INSERT INTO locations (building_name, area_name, floor_number)
        VALUES (?, ?, ?)
        ON CONFLICT (building_name, area_name, floor_number) DO NOTHING
        """,
        STARTER_LOCATIONS,
    )
    db.commit()


def _make_issue_reporter_optional(db):
    """Allow reports without accounts while preserving existing issue records."""
    user_id_column = next(
        column for column in db.execute("PRAGMA table_info(issues)")
        if column["name"] == "user_id"
    )
    if not user_id_column["notnull"]:
        return

    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE issues_new (
                issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT NOT NULL CHECK (length(trim(title)) > 0),
                description TEXT NOT NULL CHECK (length(trim(description)) > 0),
                category TEXT NOT NULL CHECK (length(trim(category)) > 0),
                location_id INTEGER NOT NULL,
                photo_path TEXT,
                priority TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low', 'normal', 'high', 'critical')),
                status TEXT NOT NULL DEFAULT 'submitted'
                    CHECK (status IN ('submitted', 'under_review', 'in_progress', 'resolved', 'closed')),
                assigned_to INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
                FOREIGN KEY (location_id) REFERENCES locations (location_id) ON DELETE RESTRICT,
                FOREIGN KEY (assigned_to) REFERENCES users (user_id) ON DELETE SET NULL
            );
            INSERT INTO issues_new (
                issue_id, user_id, title, description, category, location_id,
                photo_path, priority, status, assigned_to, created_at
            )
            SELECT
                issue_id, user_id, title, description, category, location_id,
                photo_path,
                CASE
                    WHEN priority = 'medium' THEN 'normal'
                    WHEN priority = 'urgent' THEN 'critical'
                    ELSE priority
                END,
                status, assigned_to, created_at
            FROM issues;
            DROP TABLE issues;
            ALTER TABLE issues_new RENAME TO issues;
            COMMIT;
            """
        )
    except sqlite3.Error:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _normalize_issue_priority(db):
    """Migrate old priority names without dropping reports."""
    table = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
        ("table", "issues"),
    ).fetchone()
    if table is None or not any(value in table["sql"].lower() for value in ("'medium'", "'urgent'")):
        return

    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE issues_new (
                issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT NOT NULL CHECK (length(trim(title)) > 0),
                description TEXT NOT NULL CHECK (length(trim(description)) > 0),
                category TEXT NOT NULL CHECK (length(trim(category)) > 0),
                location_id INTEGER NOT NULL,
                photo_path TEXT,
                priority TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low', 'normal', 'high', 'critical')),
                status TEXT NOT NULL DEFAULT 'submitted'
                    CHECK (status IN ('submitted', 'under_review', 'in_progress', 'resolved', 'closed')),
                assigned_to INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE RESTRICT,
                FOREIGN KEY (location_id) REFERENCES locations (location_id) ON DELETE RESTRICT,
                FOREIGN KEY (assigned_to) REFERENCES users (user_id) ON DELETE SET NULL
            );
            INSERT INTO issues_new (
                issue_id, user_id, title, description, category, location_id,
                photo_path, priority, status, assigned_to, created_at
            )
            SELECT
                issue_id, user_id, title, description, category, location_id,
                photo_path,
                CASE
                    WHEN priority = 'medium' THEN 'normal'
                    WHEN priority = 'urgent' THEN 'critical'
                    ELSE priority
                END,
                status, assigned_to, created_at
            FROM issues;
            DROP TABLE issues;
            ALTER TABLE issues_new RENAME TO issues;
            COMMIT;
            """
        )
    except sqlite3.Error:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _restrict_user_roles(db):
    """Add the maintenance role and preserve legacy staff as maintenance users."""
    table = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
        ("table", "users"),
    ).fetchone()
    table_sql = table["sql"].lower() if table else ""
    if table is None or ("'maintenance'" in table_sql and "'staff'" not in table_sql):
        return

    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE users_new (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL CHECK (length(trim(name)) > 0),
                email TEXT NOT NULL COLLATE NOCASE UNIQUE
                    CHECK (length(trim(email)) > 0),
                password_hash TEXT NOT NULL CHECK (length(password_hash) > 0),
                role TEXT NOT NULL CHECK (role IN ('student', 'maintenance', 'admin'))
            );
            INSERT INTO users_new (user_id, name, email, password_hash, role)
            SELECT
                user_id, name, email, password_hash,
                CASE
                    WHEN role = 'admin' THEN 'admin'
                    WHEN role IN ('staff', 'maintenance') THEN 'maintenance'
                    ELSE 'student'
                END
            FROM users;
            DROP TABLE users;
            ALTER TABLE users_new RENAME TO users;
            COMMIT;
            """
        )
    except sqlite3.Error:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _add_issue_history_assignment_fields(db):
    """Add event metadata to old history tables without rewriting existing events."""
    columns = {
        column["name"]
        for column in db.execute("PRAGMA table_info(issue_history)")
    }
    if "event_type" not in columns:
        db.execute(
            """
            ALTER TABLE issue_history ADD COLUMN event_type TEXT NOT NULL DEFAULT 'status'
                CHECK (event_type IN ('status', 'assignment'))
            """
        )
    if "old_assigned_to" not in columns:
        db.execute(
            """
            ALTER TABLE issue_history ADD COLUMN old_assigned_to INTEGER
                REFERENCES users (user_id) ON DELETE SET NULL
            """
        )
    if "new_assigned_to" not in columns:
        db.execute(
            """
            ALTER TABLE issue_history ADD COLUMN new_assigned_to INTEGER
                REFERENCES users (user_id) ON DELETE SET NULL
            """
        )


def get_or_create_location(building_name, area_name, floor_number):
    """Find a campus location or add it if it has not been listed before."""
    db = get_db()
    db.execute(
        """
        INSERT INTO locations (building_name, area_name, floor_number)
        VALUES (?, ?, ?)
        ON CONFLICT (building_name, area_name, floor_number) DO NOTHING
        """,
        (building_name, area_name, floor_number),
    )
    location = db.execute(
        """
        SELECT location_id FROM locations
        WHERE building_name = ? AND area_name = ? AND floor_number = ?
        """,
        (building_name, area_name, floor_number),
    ).fetchone()
    return location["location_id"]


def create_issue(user_id, title, description, category, location_id, photo_path=None):
    """Save a report and its initial status history using parameterized SQL."""
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO issues (
            user_id, title, description, category, location_id, photo_path, priority, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, title, description, category, location_id, photo_path, "normal", "submitted"),
    )
    issue_id = cursor.lastrowid
    db.execute(
        """
        INSERT INTO issue_history (issue_id, old_status, new_status, updated_by, comment)
        VALUES (?, ?, ?, ?, ?)
        """,
        (issue_id, None, "submitted", user_id, "Report submitted"),
    )
    db.commit()
    return issue_id


def close_db(error=None):
    """Close the connection at the end of the request, if one was opened."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    """Register database cleanup with the Flask application."""
    app.teardown_appcontext(close_db)