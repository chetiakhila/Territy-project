from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
from datetime import datetime
from urllib.request import urlopen
import json
import os
import time
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "telangana_demo_secret_key_change_before_deployment"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "land_registration.db")

# Official EC service link listed by the Telangana State Portal
OFFICIAL_EC_URL = "https://registration.telangana.gov.in/ec.htm"

REGIONS_URL = "https://raw.githubusercontent.com/mchittineni/india-village-finder/main/telangana/web/data/regions.json"
VILLAGES_URL = "https://raw.githubusercontent.com/mchittineni/india-village-finder/main/telangana/web/data/villages.json"

LOCATION_CACHE_DIR = os.path.join(BASE_DIR, "static", "data")
_location_cache = {"data": None, "loaded_at": 0}


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def display_timestamp():
    return datetime.now().strftime("%d-%m-%Y %H:%M")


# ==========================================
# LOCATION DATA
# ==========================================

def read_location_cache(filename):
    path = os.path.join(LOCATION_CACHE_DIR, filename)

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError):
            return None

    return None


def save_location_cache(filename, data):
    os.makedirs(LOCATION_CACHE_DIR, exist_ok=True)
    path = os.path.join(LOCATION_CACHE_DIR, filename)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False)


def get_location_data():
    if _location_cache["data"] is not None:
        if time.time() - _location_cache["loaded_at"] < 86400:
            return _location_cache["data"]

    regions = read_location_cache("telangana_regions.json")
    villages = read_location_cache("telangana_villages.json")

    if regions is None or villages is None:
        try:
            with urlopen(REGIONS_URL, timeout=15) as response:
                regions = json.loads(response.read().decode("utf-8"))

            with urlopen(VILLAGES_URL, timeout=20) as response:
                villages = json.loads(response.read().decode("utf-8"))

            save_location_cache("telangana_regions.json", regions)
            save_location_cache("telangana_villages.json", villages)

        except Exception:
            return None

    data = {"regions": regions, "villages": villages}

    _location_cache["data"] = data
    _location_cache["loaded_at"] = time.time()

    return data


@app.route("/api/locations/districts")
def location_districts():
    data = get_location_data()

    if not data:
        return jsonify({
            "error": "Location data unavailable. Check your internet connection."
        }), 503

    districts = [
        {"id": item["i"], "name": item["n"]}
        for item in data["regions"].get("districts", [])
    ]

    return jsonify(districts)


@app.route("/api/locations/mandals")
def location_mandals():
    district_id = request.args.get("district_id", type=int)

    if district_id is None:
        return jsonify({"error": "District ID required"}), 400

    data = get_location_data()

    if not data:
        return jsonify({"error": "Location data unavailable"}), 503

    mandals = [
        {"id": item["i"], "name": item["n"]}
        for item in data["regions"].get("mandals", [])
        if item.get("d") == district_id
    ]

    return jsonify(mandals)


@app.route("/api/locations/villages")
def location_villages():
    mandal_id = request.args.get("mandal_id", type=int)

    if mandal_id is None:
        return jsonify({"error": "Mandal ID required"}), 400

    data = get_location_data()

    if not data:
        return jsonify({"error": "Location data unavailable"}), 503

    rows = data["villages"].get("rows", [])

    villages = sorted({
        row[0]
        for row in rows
        if len(row) > 1 and row[1] == mandal_id and row[0]
    }, key=str.casefold)

    return jsonify([{"name": village} for village in villages])


# ==========================================
# DATABASE TABLES AND SAFE MIGRATIONS
# ==========================================

def add_column_if_missing(conn, table, column, data_type):
    existing_columns = {
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in existing_columns:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {data_type}"
        )


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            district TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS property_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_number TEXT,
            district TEXT,
            village TEXT,
            survey_number TEXT,
            search_date TEXT,
            user_id INTEGER,
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_number TEXT,
            activity TEXT,
            activity_date TEXT,
            status TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS encumbrance_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            district TEXT,
            mandal TEXT,
            village TEXT,
            survey_number TEXT,
            from_date TEXT,
            to_date TEXT,
            request_date TEXT,
            search_by TEXT,
            document_number TEXT,
            registration_year TEXT,
            sro TEXT,
            plot_number TEXT,
            house_number TEXT,
            user_id INTEGER,
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS verification_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_number TEXT,
            registration_year TEXT,
            district TEXT,
            request_date TEXT,
            user_id INTEGER,
            created_at TEXT
        )
    """)

    # Add missing columns to databases created by older versions.
    migrations = {
        "property_searches": {
            "user_id": "INTEGER",
            "created_at": "TEXT"
        },
        "encumbrance_requests": {
            "search_by": "TEXT",
            "document_number": "TEXT",
            "registration_year": "TEXT",
            "sro": "TEXT",
            "plot_number": "TEXT",
            "house_number": "TEXT",
            "mandal": "TEXT",
            "user_id": "INTEGER",
            "created_at": "TEXT"
        },
        "verification_requests": {
            "user_id": "INTEGER",
            "created_at": "TEXT"
        }
    }

    for table, columns in migrations.items():
        for column, data_type in columns.items():
            add_column_if_missing(conn, table, column, data_type)

    # Correct the wording of older demo activity entries.
    conn.execute("""
        UPDATE activity_logs
        SET status = 'Historical Demo Entry — Not Official'
        WHERE status = 'Demo Record Generated'
    """)

    conn.commit()
    conn.close()


# ==========================================
# SAVE ACTIVITY
# ==========================================

def save_activity(reference, activity, status="Details Saved in TERRITY"):
    conn = get_db()

    conn.execute("""
        INSERT INTO activity_logs
        (reference_number, activity, activity_date, status)
        VALUES (?, ?, ?, ?)
    """, (
        reference,
        activity,
        display_timestamp(),
        status
    ))

    conn.commit()
    conn.close()


# ==========================================
# LOGIN
# ==========================================

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == "admin" and password == "1234":
            session.clear()
            session["admin"] = True
            session["user_name"] = "Demo Administrator"
            return redirect("/admin")

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (username.lower(),)
        ).fetchone()

        conn.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["full_name"]
            return redirect("/dashboard")

        return render_template(
            "login.html",
            error="Invalid email or password."
        )

    return render_template("login.html")


# ==========================================
# REGISTRATION
# ==========================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        district = request.form.get("district", "").strip()

        if not full_name or not email or not password:
            return render_template(
                "register.html",
                error="Please fill in all required fields."
            )

        if len(password) < 6:
            return render_template(
                "register.html",
                error="Password must contain at least 6 characters."
            )

        hashed_password = generate_password_hash(password)
        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO users
                (full_name, email, password, district)
                VALUES (?, ?, ?, ?)
            """, (full_name, email, hashed_password, district))

            conn.commit()
            conn.close()

            return render_template(
                "register.html",
                success="Account created successfully! Please log in."
            )

        except sqlite3.IntegrityError:
            conn.close()

            return render_template(
                "register.html",
                error="This email is already registered."
            )

    return render_template("register.html")


# ==========================================
# LOGOUT
# ==========================================

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ==========================================
# USER DASHBOARD
# ==========================================

@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        return redirect("/")

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    conn.close()

    if not user:
        session.clear()
        return redirect("/")

    return render_template("dashboard.html", user=user)


# ==========================================
# ADMIN DASHBOARD
# ==========================================

@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect("/")

    conn = get_db()

    total_searches = conn.execute(
        "SELECT COUNT(*) FROM property_searches"
    ).fetchone()[0]

    total_records = conn.execute(
        "SELECT COUNT(*) FROM activity_logs"
    ).fetchone()[0]

    ec_count = conn.execute(
        "SELECT COUNT(*) FROM encumbrance_requests"
    ).fetchone()[0]

    verification_count = conn.execute(
        "SELECT COUNT(*) FROM verification_requests"
    ).fetchone()[0]

    users = conn.execute("""
        SELECT id, full_name, email, district
        FROM users ORDER BY id DESC
    """).fetchall()

    activities = conn.execute("""
        SELECT * FROM activity_logs ORDER BY id DESC
    """).fetchall()

    total_users = len(users)
    conn.close()

    return render_template(
        "admin.html",
        total_searches=total_searches,
        total_records=total_records,
        ec_count=ec_count,
        verification_count=verification_count,
        users=users,
        activities=activities,
        total_users=total_users
    )


# ==========================================
# USER DETAILS
# ==========================================

@app.route("/user-details")
def user_details():
    if not session.get("admin"):
        return redirect("/")

    return render_template("user_details.html")


# ==========================================
# ENCUMBRANCE CERTIFICATE
# ==========================================

@app.route("/encumbrance", methods=["GET", "POST"])
def encumbrance():
    if not session.get("user_id"):
        return redirect("/")

    if request.method == "POST":
        search_by = request.form.get("search_by", "").strip()

        document_number = request.form.get("document_number", "").strip()
        registration_year = request.form.get("registration_year", "").strip()
        sro = request.form.get("sro", "").strip()

        district = request.form.get("district", "").strip()
        mandal = request.form.get("mandal", "").strip()
        village = request.form.get("village", "").strip()

        survey_number = request.form.get("survey_number", "").strip()
        plot_number = request.form.get("plot_number", "").strip()
        house_number = request.form.get("house_number", "").strip()

        from_date = request.form.get("from_date", "").strip()
        to_date = request.form.get("to_date", "").strip()
        period = request.form.get("period", "").strip()

        if search_by == "document":
            if not document_number or not registration_year or not sro:
                return render_template(
                    "encumbrance.html",
                    error="Please enter Document Number, Registration Year and SRO."
                )

        elif search_by == "property":
            if not district or not mandal or not village or not survey_number:
                return render_template(
                    "encumbrance.html",
                    error="Please select District, Mandal, Village and enter Survey Number."
                )

        else:
            return render_template(
                "encumbrance.html",
                error="Please select a search method."
            )

        conn = get_db()

        cursor = conn.execute("""
            INSERT INTO encumbrance_requests (
                district, mandal, village, survey_number,
                from_date, to_date, request_date, search_by,
                document_number, registration_year, sro,
                plot_number, house_number, user_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            district, mandal, village, survey_number,
            from_date, to_date, display_timestamp(), search_by,
            document_number, registration_year, sro,
            plot_number, house_number, session["user_id"],
            current_timestamp()
        ))

        reference = "EC-" + str(cursor.lastrowid)

        conn.commit()
        conn.close()

        save_activity(
            reference,
            "Encumbrance Certificate",
            "Details Saved — Official Submission Pending"
        )

        search_details = {
            "search_by": search_by,
            "document_number": document_number,
            "registration_year": registration_year,
            "sro": sro,
            "district": district,
            "mandal": mandal,
            "village": village,
            "survey_number": survey_number,
            "plot_number": plot_number,
            "house_number": house_number,
            "from_date": from_date,
            "to_date": to_date,
            "period": period
        }

        return render_template(
            "encumbrance.html",
            saved=True,
            reference=reference,
            official_url=OFFICIAL_EC_URL,
            search_by=search_by,
            search_details=search_details
        )

    return render_template("encumbrance.html")


# ==========================================
# DOCUMENT VERIFICATION
# ==========================================

@app.route("/verification", methods=["GET", "POST"])
def verification():
    if not session.get("user_id"):
        return redirect("/")

    if request.method == "POST":
        document_number = request.form.get("document_number", "").strip()
        registration_year = request.form.get("registration_year", "").strip()
        district = request.form.get("district", "").strip()

        conn = get_db()

        cursor = conn.execute("""
            INSERT INTO verification_requests
            (document_number, registration_year, district,
             request_date, user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            document_number,
            registration_year,
            district,
            display_timestamp(),
            session["user_id"],
            current_timestamp()
        ))

        reference = "VER-" + str(cursor.lastrowid)

        conn.commit()
        conn.close()

        save_activity(
            reference,
            "Document Verification",
            "Not Verified — Official Check Required"
        )

        return render_template(
            "verification.html",
            saved=True,
            reference=reference
        )

    return render_template("verification.html")


# ==========================================
# USER PROFILE
# ==========================================

@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect("/")

    conn = get_db()

    user = conn.execute("""
        SELECT id, full_name, email, district
        FROM users WHERE id = ?
    """, (session["user_id"],)).fetchone()

    conn.close()

    if not user:
        session.clear()
        return redirect("/")

    return render_template("profile.html", user=user)


# ==========================================
# INSTRUCTIONS
# ==========================================

@app.route("/instructions")
def instructions():
    if not session.get("user_id"):
        return redirect("/")

    return render_template("instructions.html")


# ==========================================
# PROPERTY SEARCH PAGE
# ==========================================

@app.route("/search")
def search():
    if not session.get("user_id"):
        return redirect("/")

    return render_template("search.html")


# ==========================================
# UNIFIED REGISTRATION HISTORY
# ==========================================

@app.route("/history")
def history():
    if not session.get("user_id") and not session.get("admin"):
        return redirect("/")

    conn = get_db()

    # Administrators can see all records.
    # Regular users can see only their own records.
    if session.get("admin"):
        owner_filter = ""
        params = ()
    else:
        owner_filter = "WHERE user_id = ?"
        params = (session["user_id"],)

    records = conn.execute(f"""
        SELECT *
        FROM (
            SELECT
                'DEMO-' || id AS reference_number,
                'Property Search' AS service,
                COALESCE(document_number, '—') AS document_number,
                COALESCE(district, '—') AS district,
                COALESCE(village, '—') AS village,
                COALESCE(survey_number, '—') AS survey_number,
                COALESCE(search_date, '—') AS record_date,
                'Saved' AS status,
                COALESCE(created_at, '') AS sort_date,
                user_id
            FROM property_searches

            UNION ALL

            SELECT
                'EC-' || id AS reference_number,
                'Encumbrance Certificate' AS service,
                CASE
                    WHEN search_by = 'document'
                    THEN COALESCE(document_number, '—')
                    ELSE 'Property-based search'
                END AS document_number,
                COALESCE(district, '—') AS district,
                COALESCE(village, '—') AS village,
                COALESCE(survey_number, '—') AS survey_number,
                COALESCE(request_date, '—') AS record_date,
                'Details Saved — Official Submission Pending' AS status,
                COALESCE(created_at, '') AS sort_date,
                user_id
            FROM encumbrance_requests

            UNION ALL

            SELECT
                'VER-' || id AS reference_number,
                'Document Verification' AS service,
                COALESCE(document_number, '—') AS document_number,
                COALESCE(district, '—') AS district,
                '—' AS village,
                '—' AS survey_number,
                COALESCE(request_date, '—') AS record_date,
                'Not Verified — Official Check Required' AS status,
                COALESCE(created_at, '') AS sort_date,
                user_id
            FROM verification_requests
        )
        {owner_filter}
        ORDER BY
            CASE WHEN sort_date = '' THEN 1 ELSE 0 END,
            sort_date DESC,
            reference_number DESC
    """, params).fetchall()

    conn.close()

    return render_template(
        "history.html",
        records=records
    )


# ==========================================
# PROPERTY DETAILS
# ==========================================

@app.route("/property", methods=["POST"])
def property_details():
    if not session.get("user_id"):
        return redirect("/")

    document_number = request.form.get("document_number", "").strip()
    district = request.form.get("district", "").strip()
    village = request.form.get("village", "").strip()
    survey_number = request.form.get("survey_number", "").strip()

    search_date = display_timestamp()

    conn = get_db()

    cursor = conn.execute("""
        INSERT INTO property_searches
        (document_number, district, village, survey_number,
         search_date, user_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        document_number,
        district,
        village,
        survey_number,
        search_date,
        session["user_id"],
        current_timestamp()
    ))

    reference = "DEMO-" + str(cursor.lastrowid)

    conn.commit()
    conn.close()

    save_activity(reference, "Property Search", "Search Details Saved")

    return render_template(
        "property.html",
        document_number=document_number,
        district=district,
        village=village,
        survey_number=survey_number
    )


# ==========================================
# START APPLICATION
# ==========================================

if __name__ == "__main__":
    init_db()
    app.run(debug=True)