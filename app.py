"""
Project Allocation System - Flask Application
Run: python app.py
Visit: http://localhost:5500
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, csv, io, json
import openpyxl
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = "project_alloc_secret_2024"
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

DB = 'instance/project_allocation.db'
os.makedirs('uploads', exist_ok=True)
os.makedirs('uploads/papers', exist_ok=True)
os.makedirs('instance', exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ─── DATABASE ───────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript('''
        CREATE TABLE IF NOT EXISTS coordinator (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS guide (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            department TEXT,
            expertise TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS student (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            prn TEXT UNIQUE NOT NULL,
            division TEXT,
            department TEXT,
            email TEXT UNIQUE,
            password TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS project_group (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_lead_id INTEGER,
            project_title TEXT,
            title_finalized INTEGER DEFAULT 0,
            guide_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(team_lead_id) REFERENCES student(id),
            FOREIGN KEY(guide_id) REFERENCES guide(id)
        );
        CREATE TABLE IF NOT EXISTS group_member (
            group_id INTEGER,
            student_id INTEGER,
            PRIMARY KEY(group_id, student_id),
            FOREIGN KEY(group_id) REFERENCES project_group(id),
            FOREIGN KEY(student_id) REFERENCES student(id)
        );
        CREATE TABLE IF NOT EXISTS project_title (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guide_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(guide_id) REFERENCES guide(id)
        );
        CREATE TABLE IF NOT EXISTS paper_publication (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            stage INTEGER NOT NULL CHECK(stage IN (1, 2)),
            paper_title TEXT NOT NULL,
            journal_name TEXT NOT NULL,
            volume_no TEXT NOT NULL,
            issue TEXT NOT NULL,
            timeline TEXT NOT NULL,
            e_issn TEXT NOT NULL,
            pdf_filename TEXT,
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(group_id) REFERENCES project_group(id),
            UNIQUE(group_id, stage)
        );
        CREATE TABLE IF NOT EXISTS marks_column (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            max_marks INTEGER NOT NULL CHECK(max_marks >= 0),
            sort_order INTEGER NOT NULL DEFAULT 0,
            stage INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS marks_entry (
            student_id INTEGER NOT NULL,
            column_id INTEGER NOT NULL,
            marks REAL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(student_id, column_id),
            FOREIGN KEY(student_id) REFERENCES student(id),
            FOREIGN KEY(column_id) REFERENCES marks_column(id)
        );
        CREATE TABLE IF NOT EXISTS marks_template (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            academic_year TEXT NOT NULL,
            evaluation_title TEXT NOT NULL,
            stage_title TEXT NOT NULL,
            class_name TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    # ── Auto-migrations ─────────────────────────────────────────────────────
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(student)").fetchall()]
    if 'roll_no' in existing_cols and 'prn' not in existing_cols:
        c.executescript('''
            ALTER TABLE student RENAME TO student_old;
            CREATE TABLE student (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                prn TEXT UNIQUE NOT NULL,
                division TEXT,
                department TEXT,
                email TEXT UNIQUE,
                password TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO student (id, name, prn, department, email, password, created_at)
                SELECT id, name, roll_no, department, email, password, created_at FROM student_old;
            DROP TABLE student_old;
        ''')
    elif 'prn' in existing_cols and 'division' not in existing_cols:
        c.execute("ALTER TABLE student ADD COLUMN division TEXT")

    pg_cols = [row[1] for row in c.execute("PRAGMA table_info(project_group)").fetchall()]
    if 'title_finalized' not in pg_cols:
        c.execute("ALTER TABLE project_group ADD COLUMN title_finalized INTEGER DEFAULT 0")

    marks_cols = [row[1] for row in c.execute("PRAGMA table_info(marks_column)").fetchall()]
    if 'stage' not in marks_cols:
        c.execute("ALTER TABLE marks_column ADD COLUMN stage INTEGER NOT NULL DEFAULT 1")

    # Default coordinator
    existing = c.execute("SELECT id FROM coordinator WHERE email='coordinator@college.edu'").fetchone()
    if not existing:
        c.execute("INSERT INTO coordinator (name, email, password) VALUES (?, ?, ?)",
                  ("Admin Coordinator", "coordinator@college.edu",
                   generate_password_hash("coord123")))

    tmpl = c.execute("SELECT id FROM marks_template WHERE id=1").fetchone()
    if not tmpl:
        c.execute(
            "INSERT INTO marks_template (id, academic_year, evaluation_title, stage_title, class_name) VALUES (1, ?, ?, ?, ?)",
            ("Academic year 2024-25", "Evaluation sheet", "Project Stage-I Progress Presentation", "B.Tech CSE (Final year)")
        )
    conn.commit()
    conn.close()

# ─── AUTH DECORATORS ────────────────────────────────────────────────────────
def login_required(role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') != role:
                flash('Please login to continue.', 'warning')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ─── ROUTES: AUTH ───────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role')
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        conn = get_db()

        if role == 'coordinator':
            user = conn.execute("SELECT * FROM coordinator WHERE email=?", (email,)).fetchone()
            if user and check_password_hash(user['password'], password):
                session['role'] = 'coordinator'
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                conn.close()
                return redirect(url_for('coord_dashboard'))
            flash('Invalid coordinator credentials.', 'error')

        elif role == 'guide':
            user = conn.execute("SELECT * FROM guide WHERE email=?", (email,)).fetchone()
            if user and check_password_hash(user['password'], password):
                session['role'] = 'guide'
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                conn.close()
                return redirect(url_for('guide_dashboard'))
            flash('Invalid guide credentials.', 'error')

        elif role == 'student':
            user = conn.execute("SELECT * FROM student WHERE email=?", (email,)).fetchone()
            if user and check_password_hash(user['password'], password):
                session['role'] = 'student'
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                conn.close()
                return redirect(url_for('student_dashboard'))
            flash('Invalid student credentials. Use your Email as login ID and PRN as password.', 'error')

        conn.close()
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── SERVE UPLOADED PAPERS ──────────────────────────────────────────────────
@app.route('/view-paper/<filename>')
def serve_paper(filename):
    if session.get('role') not in ('coordinator', 'guide', 'student'):
        return redirect(url_for('login'))
    papers_dir = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], 'papers'))
    return send_from_directory(papers_dir, filename)

# ─── ROUTES: COORDINATOR ────────────────────────────────────────────────────
@app.route('/coordinator/dashboard')
@login_required('coordinator')
def coord_dashboard():
    conn = get_db()
    stats = {
        'students': conn.execute("SELECT COUNT(*) FROM student").fetchone()[0],
        'guides': conn.execute("SELECT COUNT(*) FROM guide").fetchone()[0],
        'groups': conn.execute("SELECT COUNT(*) FROM project_group").fetchone()[0],
        'allocated': conn.execute("SELECT COUNT(*) FROM project_group WHERE guide_id IS NOT NULL").fetchone()[0],
        'finalized': conn.execute("SELECT COUNT(*) FROM project_group WHERE title_finalized=1").fetchone()[0],
        'pending': conn.execute("SELECT COUNT(*) FROM project_group WHERE title_finalized=0 AND project_title IS NOT NULL AND project_title != ''").fetchone()[0],
        'papers_s1': conn.execute("SELECT COUNT(*) FROM paper_publication WHERE stage=1").fetchone()[0],
        'papers_s2': conn.execute("SELECT COUNT(*) FROM paper_publication WHERE stage=2").fetchone()[0],
    }
    recent_groups = conn.execute("""
        SELECT pg.id, pg.project_title, pg.guide_id, pg.title_finalized,
               s.name as lead_name,
               g.name as guide_name,
               (SELECT COUNT(*) FROM group_member WHERE group_id=pg.id) as member_count
        FROM project_group pg
        LEFT JOIN student s ON pg.team_lead_id = s.id
        LEFT JOIN guide g ON pg.guide_id = g.id
        ORDER BY pg.created_at DESC LIMIT 5
    """).fetchall()
    conn.close()
    return render_template('coordinator/dashboard.html', stats=stats, recent_groups=recent_groups)

@app.route('/coordinator/students')
@login_required('coordinator')
def coord_students():
    conn = get_db()
    students = conn.execute("""
        SELECT s.*,
               CASE WHEN gm.student_id IS NOT NULL THEN 1 ELSE 0 END as in_group
        FROM student s
        LEFT JOIN group_member gm ON s.id = gm.student_id
        ORDER BY s.name
    """).fetchall()
    conn.close()
    return render_template('coordinator/students.html', students=students)

@app.route('/coordinator/students/upload', methods=['POST'])
@login_required('coordinator')
def upload_students():
    file = request.files.get('file')
    if not file:
        flash('No file selected.', 'error')
        return redirect(url_for('coord_students'))

    filename = file.filename.lower()
    if not filename.endswith(('.xlsx', '.xls')):
        flash('Please upload an Excel file (.xlsx or .xls).', 'error')
        return redirect(url_for('coord_students'))

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file.read()), data_only=True)
        ws = wb.active
    except Exception as e:
        flash(f'Could not read Excel file: {str(e)}', 'error')
        return redirect(url_for('coord_students'))

    headers = []
    for cell in ws[1]:
        val = str(cell.value).strip().lower() if cell.value is not None else ''
        headers.append(val)

    conn = get_db()
    count = 0
    skipped = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if all(v is None for v in row):
            continue
        row_data = {}
        for i, val in enumerate(row):
            if i < len(headers):
                row_data[headers[i]] = str(val).strip() if val is not None else ''

        name  = row_data.get('name', '')
        prn   = row_data.get('prn', '')
        div   = row_data.get('division', row_data.get('div', ''))
        dept  = row_data.get('department', row_data.get('dept', ''))
        email = row_data.get('email', '')

        if not name or not prn or not email:
            skipped += 1
            continue
        try:
            conn.execute(
                "INSERT OR IGNORE INTO student (name, prn, division, department, email, password) VALUES (?,?,?,?,?,?)",
                (name, prn, div, dept, email, generate_password_hash(prn))
            )
            count += 1
        except Exception:
            skipped += 1

    conn.commit()
    conn.close()
    msg = f'Successfully uploaded {count} student(s) from Excel.'
    if skipped:
        msg += f' {skipped} row(s) skipped (missing data or duplicate PRN/email).'
    flash(msg, 'success')
    return redirect(url_for('coord_students'))

@app.route('/coordinator/students/delete/<int:sid>', methods=['POST'])
@login_required('coordinator')
def delete_student(sid):
    conn = get_db()
    conn.execute("DELETE FROM group_member WHERE student_id=?", (sid,))
    conn.execute("DELETE FROM student WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    flash('Student removed.', 'success')
    return redirect(url_for('coord_students'))

@app.route('/coordinator/guides')
@login_required('coordinator')
def coord_guides():
    conn = get_db()
    guides = conn.execute("""
        SELECT g.*,
               (SELECT COUNT(*) FROM project_group pg WHERE pg.guide_id = g.id) as group_count,
               (SELECT COUNT(*) FROM project_title pt WHERE pt.guide_id = g.id) as title_count
        FROM guide g ORDER BY g.name
    """).fetchall()
    conn.close()
    return render_template('coordinator/guides.html', guides=guides)

@app.route('/coordinator/guides/add', methods=['POST'])
@login_required('coordinator')
def add_guide():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    department = request.form.get('department', '').strip()
    expertise = request.form.get('expertise', '').strip()
    if not name or not email or not password:
        flash('Name, email and password are required.', 'error')
        return redirect(url_for('coord_guides'))
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO guide (name, email, password, department, expertise) VALUES (?,?,?,?,?)",
            (name, email, generate_password_hash(password), department, expertise)
        )
        conn.commit()
        flash(f'Guide {name} added successfully.', 'success')
    except sqlite3.IntegrityError:
        flash('Email already exists.', 'error')
    conn.close()
    return redirect(url_for('coord_guides'))

@app.route('/coordinator/guides/delete/<int:gid>', methods=['POST'])
@login_required('coordinator')
def delete_guide(gid):
    conn = get_db()
    conn.execute("DELETE FROM project_title WHERE guide_id=?", (gid,))
    conn.execute("UPDATE project_group SET guide_id=NULL WHERE guide_id=?", (gid,))
    conn.execute("DELETE FROM guide WHERE id=?", (gid,))
    conn.commit()
    conn.close()
    flash('Guide removed.', 'success')
    return redirect(url_for('coord_guides'))

@app.route('/coordinator/groups')
@login_required('coordinator')
def coord_groups():
    conn = get_db()
    groups = conn.execute("""
        SELECT pg.id, pg.project_title, pg.title_finalized, pg.guide_id,
               s.name as lead_name, s.prn as lead_roll,
               g.name as guide_name,
               (SELECT COUNT(*) FROM group_member WHERE group_id=pg.id) as member_count
        FROM project_group pg
        LEFT JOIN student s ON pg.team_lead_id = s.id
        LEFT JOIN guide g ON pg.guide_id = g.id
        ORDER BY pg.created_at DESC
    """).fetchall()
    guides = conn.execute("SELECT id, name, department FROM guide ORDER BY name").fetchall()

    groups_with_members = []
    for grp in groups:
        members = conn.execute("""
            SELECT s.name, s.prn FROM group_member gm
            JOIN student s ON gm.student_id = s.id
            WHERE gm.group_id=?
        """, (grp['id'],)).fetchall()
        papers = conn.execute(
            "SELECT stage FROM paper_publication WHERE group_id=?", (grp['id'],)
        ).fetchall()
        paper_stages = [p['stage'] for p in papers]
        groups_with_members.append({'group': grp, 'members': members, 'paper_stages': paper_stages})

    conn.close()
    return render_template('coordinator/groups.html', groups=groups_with_members, guides=guides)

@app.route('/coordinator/groups/allocate', methods=['POST'])
@login_required('coordinator')
def allocate_guide():
    group_id = request.form.get('group_id')
    guide_id = request.form.get('guide_id') or None
    conn = get_db()
    conn.execute("UPDATE project_group SET guide_id=? WHERE id=?", (guide_id, group_id))
    conn.commit()
    conn.close()
    flash('Guide allocated successfully.', 'success')
    return redirect(url_for('coord_groups'))

@app.route('/coordinator/groups/finalize-title', methods=['POST'])
@login_required('coordinator')
def finalize_title():
    group_id = request.form.get('group_id')
    conn = get_db()
    grp = conn.execute("SELECT project_title, title_finalized FROM project_group WHERE id=?", (group_id,)).fetchone()
    if not grp:
        flash('Group not found.', 'error')
        conn.close()
        return redirect(url_for('coord_groups'))
    if not grp['project_title']:
        flash('Cannot finalize — the group has not submitted a project title yet.', 'error')
        conn.close()
        return redirect(url_for('coord_groups'))
    new_status = 0 if grp['title_finalized'] else 1
    conn.execute("UPDATE project_group SET title_finalized=? WHERE id=?", (new_status, group_id))
    conn.commit()
    conn.close()
    if new_status:
        flash('✅ Project title finalized successfully.', 'success')
    else:
        flash('Project title un-finalized. Students can now update it.', 'warning')
    return redirect(url_for('coord_groups'))

@app.route('/coordinator/allocations')
@login_required('coordinator')
def coord_allocations():
    conn = get_db()
    guides = conn.execute("SELECT * FROM guide ORDER BY name").fetchall()
    guide_data = []
    for guide in guides:
        groups = conn.execute("""
            SELECT pg.id, pg.project_title, pg.title_finalized,
                   s.name as lead_name, s.prn as lead_roll,
                   (SELECT COUNT(*) FROM group_member WHERE group_id=pg.id) as member_count
            FROM project_group pg
            LEFT JOIN student s ON pg.team_lead_id = s.id
            WHERE pg.guide_id=?
            ORDER BY pg.created_at DESC
        """, (guide['id'],)).fetchall()
        guide_data.append({'guide': guide, 'groups': groups})
    unallocated = conn.execute("""
        SELECT pg.id, pg.project_title, pg.title_finalized,
               s.name as lead_name,
               (SELECT COUNT(*) FROM group_member WHERE group_id=pg.id) as member_count
        FROM project_group pg
        LEFT JOIN student s ON pg.team_lead_id = s.id
        WHERE pg.guide_id IS NULL
    """).fetchall()
    conn.close()
    return render_template('coordinator/allocations.html', guide_data=guide_data, unallocated=unallocated)

# ─── COORDINATOR: PAPER PUBLICATIONS VIEW ───────────────────────────────────
@app.route('/coordinator/papers')
@login_required('coordinator')
def coord_papers():
    conn = get_db()
    papers = conn.execute("""
        SELECT pp.*, pg.project_title,
               s.name as lead_name, s.prn as lead_roll,
               g.name as guide_name
        FROM paper_publication pp
        JOIN project_group pg ON pp.group_id = pg.id
        LEFT JOIN student s ON pg.team_lead_id = s.id
        LEFT JOIN guide g ON pg.guide_id = g.id
        ORDER BY pp.stage, pp.submitted_at DESC
    """).fetchall()
    conn.close()
    return render_template('coordinator/papers.html', papers=papers)

# ─── COORDINATOR: MARKS ALLOCATION ──────────────────────────────────────────
@app.route('/coordinator/marks')
@login_required('coordinator')
def coord_marks():
    conn = get_db()
    stage = request.args.get('stage', '1')
    stage = 2 if str(stage) == '2' else 1
    columns = conn.execute(
        "SELECT id, name, max_marks, sort_order FROM marks_column WHERE stage=? ORDER BY sort_order, id",
        (stage,)
    ).fetchall()

    total_max = sum(int(c['max_marks']) for c in columns)
    stage = request.args.get('stage', '1')
    stage = 2 if str(stage) == '2' else 1

    template = conn.execute(
        "SELECT academic_year, evaluation_title, stage_title, class_name FROM marks_template WHERE id=1"
    ).fetchone()
    if not template:
        template = {
            'academic_year': 'Academic year 2024-25',
            'evaluation_title': 'Evaluation sheet',
            'stage_title': 'Project Stage-I Progress Presentation',
            'class_name': 'B.Tech CSE (Final year)'
        }

    groups_raw = conn.execute("""
        SELECT pg.id as group_id, pg.created_at,
               g.name as guide_name
        FROM project_group pg
        LEFT JOIN guide g ON pg.guide_id = g.id
        ORDER BY pg.created_at, pg.id
    """).fetchall()

    members_raw = conn.execute("""
        SELECT gm.group_id, s.id as student_id, s.prn, s.name,
               CASE WHEN pg.team_lead_id = s.id THEN 1 ELSE 0 END as is_lead
        FROM group_member gm
        JOIN student s ON gm.student_id = s.id
        JOIN project_group pg ON gm.group_id = pg.id
        ORDER BY gm.group_id, s.prn
    """).fetchall()

    members_by_group = {}
    for row in members_raw:
        members_by_group.setdefault(row['group_id'], []).append({
            'id': row['student_id'],
            'prn': row['prn'],
            'name': row['name'],
            'is_lead': bool(row['is_lead']),
        })

    groups = []
    group_no = 1
    for grp in groups_raw:
        members = members_by_group.get(grp['group_id'], [])
        if not members:
            continue
        groups.append({
            'group_id': grp['group_id'],
            'group_no': group_no,
            'guide_name': grp['guide_name'] if grp['guide_name'] else None,
            'members': members,
        })
        group_no += 1

    student_ids = [m['id'] for g in groups for m in g['members']]
    marks = {}
    totals = {}
    if student_ids and columns:
        student_placeholders = ",".join(["?"] * len(student_ids))
        col_ids = [c['id'] for c in columns]
        col_placeholders = ",".join(["?"] * len(col_ids))
        mark_rows = conn.execute(
            f"""
            SELECT student_id, column_id, marks
            FROM marks_entry
            WHERE student_id IN ({student_placeholders})
              AND column_id IN ({col_placeholders})
            """,
            tuple(student_ids) + tuple(col_ids)
        ).fetchall()
        for m in mark_rows:
            key = f"{m['student_id']}:{m['column_id']}"
            marks[key] = m['marks']
            totals[m['student_id']] = totals.get(m['student_id'], 0) + (m['marks'] or 0)

    conn.close()
    today = datetime.now().strftime('%d-%m-%Y')
    return render_template(
        'coordinator/marks.html',
        groups=groups,
        columns=columns,
        marks=marks,
        totals=totals,
        total_max=total_max,
        student_count=len(student_ids),
        today=today,
        template=template,
        stage=stage,
    )

@app.route('/coordinator/marks/columns/add', methods=['POST'])
@login_required('coordinator')
def coord_marks_add_column():
    name = request.form.get('name', '').strip()
    max_marks = request.form.get('max_marks', type=int)
    stage = request.form.get('stage', type=int)
    stage = 2 if stage == 2 else 1

    if not name or max_marks is None or max_marks < 0:
        flash('Please enter a column name and valid max marks (>= 0).', 'error')
        return redirect(url_for('coord_marks', stage=stage))

    conn = get_db()
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM marks_column WHERE stage=?",
        (stage,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO marks_column (name, max_marks, sort_order, stage) VALUES (?,?,?,?)",
        (name, max_marks, next_order, stage)
    )
    conn.commit()
    conn.close()
    flash('Marks column added.', 'success')
    return redirect(url_for('coord_marks', stage=stage))

@app.route('/coordinator/marks/columns/update', methods=['POST'])
@login_required('coordinator')
def coord_marks_update_column():
    column_id = request.form.get('column_id', type=int)
    name = request.form.get('name', '').strip()
    max_marks = request.form.get('max_marks', type=int)
    stage = request.form.get('stage', type=int)
    stage = 2 if stage == 2 else 1

    if not column_id or not name or max_marks is None or max_marks < 0:
        flash('Please enter a valid column name and max marks (>= 0).', 'error')
        return redirect(url_for('coord_marks', stage=stage))

    conn = get_db()
    existing = conn.execute("SELECT id FROM marks_column WHERE id=?", (column_id,)).fetchone()
    if not existing:
        conn.close()
        flash('Column not found.', 'error')
        return redirect(url_for('coord_marks', stage=stage))

    max_existing = conn.execute(
        "SELECT COALESCE(MAX(marks), 0) FROM marks_entry WHERE column_id=?",
        (column_id,)
    ).fetchone()[0]

    if max_marks < float(max_existing or 0):
        conn.close()
        flash('Max marks cannot be less than existing marks in this column.', 'error')
        return redirect(url_for('coord_marks', stage=stage))

    conn.execute(
        "UPDATE marks_column SET name=?, max_marks=? WHERE id=?",
        (name, max_marks, column_id)
    )
    conn.commit()
    conn.close()
    flash('Marks column updated.', 'success')
    return redirect(url_for('coord_marks', stage=stage))

@app.route('/coordinator/marks/template/update', methods=['POST'])
@login_required('coordinator')
def coord_marks_update_template():
    academic_year = request.form.get('academic_year', '').strip()
    evaluation_title = request.form.get('evaluation_title', '').strip()
    stage_title = request.form.get('stage_title', '').strip()
    class_name = request.form.get('class_name', '').strip()

    if not all([academic_year, evaluation_title, stage_title, class_name]):
        flash('Please fill all template fields.', 'error')
        return redirect(url_for('coord_marks'))

    conn = get_db()
    existing = conn.execute("SELECT id FROM marks_template WHERE id=1").fetchone()
    if existing:
        conn.execute("""
            UPDATE marks_template
            SET academic_year=?, evaluation_title=?, stage_title=?, class_name=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=1
        """, (academic_year, evaluation_title, stage_title, class_name))
    else:
        conn.execute("""
            INSERT INTO marks_template (id, academic_year, evaluation_title, stage_title, class_name)
            VALUES (1, ?, ?, ?, ?)
        """, (academic_year, evaluation_title, stage_title, class_name))
    conn.commit()
    conn.close()
    flash('Template updated.', 'success')
    return redirect(url_for('coord_marks'))

@app.route('/coordinator/marks/columns/delete', methods=['POST'])
@login_required('coordinator')
def coord_marks_delete_column():
    column_id = request.form.get('column_id', type=int)
    stage = request.form.get('stage', type=int)
    stage = 2 if stage == 2 else 1
    if not column_id:
        flash('Column not found.', 'error')
        return redirect(url_for('coord_marks', stage=stage))

    conn = get_db()
    existing = conn.execute("SELECT id FROM marks_column WHERE id=?", (column_id,)).fetchone()
    if not existing:
        conn.close()
        flash('Column not found.', 'error')
        return redirect(url_for('coord_marks', stage=stage))

    conn.execute("DELETE FROM marks_entry WHERE column_id=?", (column_id,))
    conn.execute("DELETE FROM marks_column WHERE id=?", (column_id,))
    conn.commit()
    conn.close()
    flash('Marks column deleted.', 'success')
    return redirect(url_for('coord_marks', stage=stage))

@app.route('/coordinator/marks/save', methods=['POST'])
@login_required('coordinator')
def coord_marks_save():
    conn = get_db()
    stage = request.form.get('stage', type=int)
    stage = 2 if stage == 2 else 1
    cols = conn.execute("SELECT id, max_marks FROM marks_column WHERE stage=?", (stage,)).fetchall()
    max_map = {int(c['id']): float(c['max_marks']) for c in cols}

    invalid = 0
    updated = 0

    for key, value in request.form.items():
        if not key.startswith('m_'):
            continue
        parts = key.split('_')
        if len(parts) != 3:
            continue

        try:
            student_id = int(parts[1])
            column_id = int(parts[2])
        except ValueError:
            continue

        if column_id not in max_map:
            continue

        raw = (value or '').strip()
        if raw == '':
            conn.execute(
                "DELETE FROM marks_entry WHERE student_id=? AND column_id=?",
                (student_id, column_id)
            )
            continue

        try:
            marks_val = float(raw)
        except ValueError:
            invalid += 1
            continue

        if marks_val < 0 or marks_val > max_map[column_id]:
            invalid += 1
            continue

        conn.execute("""
            INSERT INTO marks_entry (student_id, column_id, marks, updated_at)
            VALUES (?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(student_id, column_id) DO UPDATE SET
                marks=excluded.marks,
                updated_at=CURRENT_TIMESTAMP
        """, (student_id, column_id, marks_val))
        updated += 1

    conn.commit()
    conn.close()

    if invalid:
        flash('Some entries were ignored (invalid or exceeded max marks).', 'warning')
    flash('Marks saved successfully.', 'success')
    return redirect(url_for('coord_marks', stage=stage))

@app.route('/coordinator/marks/export')
@login_required('coordinator')
def coord_marks_export():
    try:
        from docx import Document
        from docx.shared import Inches
        from docx.shared import Pt
        from docx.enum.section import WD_ORIENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ModuleNotFoundError:
        flash('Word export requires python-docx. Install with: pip install python-docx', 'error')
        return redirect(url_for('coord_marks'))

    conn = get_db()
    stage = request.args.get('stage', '1')
    stage = 2 if str(stage) == '2' else 1
    columns = conn.execute(
        "SELECT id, name, max_marks, sort_order FROM marks_column WHERE stage=? ORDER BY sort_order, id",
        (stage,)
    ).fetchall()
    total_max = sum(int(c['max_marks']) for c in columns)

    template = conn.execute(
        "SELECT academic_year, evaluation_title, stage_title, class_name FROM marks_template WHERE id=1"
    ).fetchone()
    if not template:
        template = {
            'academic_year': 'Academic year 2024-25',
            'evaluation_title': 'Evaluation sheet',
            'stage_title': 'Project Stage-I Progress Presentation',
            'class_name': 'B.Tech CSE (Final year)'
        }
    export_class = request.args.get('class_name', '').strip()
    if export_class:
        template['class_name'] = export_class

    groups_raw = conn.execute("""
        SELECT pg.id as group_id, pg.created_at,
               g.name as guide_name
        FROM project_group pg
        LEFT JOIN guide g ON pg.guide_id = g.id
        ORDER BY pg.created_at, pg.id
    """).fetchall()

    members_raw = conn.execute("""
        SELECT gm.group_id, s.id as student_id, s.prn, s.name,
               CASE WHEN pg.team_lead_id = s.id THEN 1 ELSE 0 END as is_lead
        FROM group_member gm
        JOIN student s ON gm.student_id = s.id
        JOIN project_group pg ON gm.group_id = pg.id
        ORDER BY gm.group_id, s.prn
    """).fetchall()

    marks_rows = []
    col_ids = [c['id'] for c in columns]
    if col_ids:
        col_placeholders = ",".join(["?"] * len(col_ids))
        marks_rows = conn.execute(
            f"SELECT student_id, column_id, marks FROM marks_entry WHERE column_id IN ({col_placeholders})",
            tuple(col_ids)
        ).fetchall()
    conn.close()

    members_by_group = {}
    for row in members_raw:
        members_by_group.setdefault(row['group_id'], []).append({
            'id': row['student_id'],
            'prn': row['prn'],
            'name': row['name'],
            'is_lead': bool(row['is_lead']),
        })

    marks_map = {(int(m['student_id']), int(m['column_id'])): m['marks'] for m in marks_rows}

    def fmt_num(val):
        if val is None:
            return ""
        try:
            num = float(val)
        except (TypeError, ValueError):
            return str(val)
        return str(int(num)) if num.is_integer() else str(num)

    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    section.left_margin = Inches(0.4)
    section.right_margin = Inches(0.4)
    section.top_margin = Inches(0.4)
    section.bottom_margin = Inches(0.4)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(template['academic_year']).bold = True

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(template['evaluation_title']).bold = True

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    stage_title = "Project Stage-II Progress Presentation II" if stage == 2 else "Project Stage-I Progress Presentation I"
    p.add_run(stage_title).bold = True

    p = doc.add_paragraph()
    p.paragraph_format.tab_stops.add_tab_stop(Inches(6.5))
    p.add_run(f"Class: {template['class_name']}")
    p.add_run("\t")
    p.add_run(f"Date: {datetime.now().strftime('%d-%m-%Y')}")

    headers = (
        ["GROUP NO.", "SR. NO.", "PRN", "NAME OF STUDENT"]
        + [f"{c['name']} ({c['max_marks']})" for c in columns]
        + [f"TOTAL ({total_max})", "NAME AND SIGN OF GUIDE"]
    )

    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = False

    hdr_cells = table.rows[0].cells
    for idx, title in enumerate(headers):
        hdr_cells[idx].text = title
        for para in hdr_cells[idx].paragraphs:
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in para.runs:
                run.font.size = Pt(9)

    sr_no = 1
    group_no = 1
    for grp in groups_raw:
        members = members_by_group.get(grp['group_id'], [])
        if not members:
            continue

        start_row = len(table.rows)
        for mem_idx, mem in enumerate(members):
            row_cells = table.add_row().cells
            row_cells[0].text = str(group_no) if mem_idx == 0 else ""
            row_cells[1].text = str(sr_no)
            row_cells[2].text = str(mem['prn'])
            name_text = str(mem['name'])
            if mem.get('is_lead'):
                name_text += " (Team Lead)"
            row_cells[3].text = name_text

            total = 0
            for col_idx, c in enumerate(columns):
                val = marks_map.get((mem['id'], int(c['id'])))
                row_cells[4 + col_idx].text = fmt_num(val)
                if val is not None:
                    total += float(val or 0)

            row_cells[4 + len(columns)].text = "" if not columns else fmt_num(total)
            row_cells[4 + len(columns) + 1].text = (grp['guide_name'] or "N/A") if mem_idx == 0 else ""

            sr_no += 1

        end_row = len(table.rows) - 1
        if end_row > start_row:
            table.cell(start_row, 0).merge(table.cell(end_row, 0))
            table.cell(start_row, len(headers) - 1).merge(table.cell(end_row, len(headers) - 1))

        group_no += 1

    # Set column widths to keep text horizontal
    def set_col_width(table_obj, col_idx, width):
        for r in table_obj.rows:
            r.cells[col_idx].width = width

    available_in = (section.page_width - section.left_margin - section.right_margin) / Inches(1)
    fixed_in = {
        'group': 0.55,
        'sr': 0.5,
        'prn': 1.05,
        'name': 2.2,
        'total': 0.7,
        'guide': 1.4
    }
    fixed_sum = sum(fixed_in.values())
    col_count = len(columns)
    per_col = 0.55
    if col_count > 0:
        per_col = max(0.55, (available_in - fixed_sum) / col_count)

    widths = [fixed_in['group'], fixed_in['sr'], fixed_in['prn'], fixed_in['name']]
    widths += [per_col for _ in range(col_count)]
    widths += [fixed_in['total'], fixed_in['guide']]

    for idx, w in enumerate(widths):
        set_col_width(table, idx, Inches(w))

    # Reduce font size across table for fit
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(8)

    out = io.BytesIO()
    doc.save(out)
    out.seek(0)

    filename = f"marks_allocation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    return send_file(
        out,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

# ─── ROUTES: GUIDE ──────────────────────────────────────────────────────────
@app.route('/guide/dashboard')
@login_required('guide')
def guide_dashboard():
    conn = get_db()
    guide_id = session['user_id']
    groups = conn.execute("""
        SELECT pg.id, pg.project_title, pg.title_finalized,
               s.name as lead_name, s.prn as lead_roll,
               (SELECT COUNT(*) FROM group_member WHERE group_id=pg.id) as member_count
        FROM project_group pg
        LEFT JOIN student s ON pg.team_lead_id = s.id
        WHERE pg.guide_id=?
        ORDER BY pg.created_at DESC
    """, (guide_id,)).fetchall()
    titles = conn.execute("SELECT * FROM project_title WHERE guide_id=? ORDER BY created_at DESC", (guide_id,)).fetchall()
    guide = conn.execute("SELECT * FROM guide WHERE id=?", (guide_id,)).fetchone()
    conn.close()
    return render_template('guide/dashboard.html', groups=groups, titles=titles, guide=guide)

@app.route('/guide/groups')
@login_required('guide')
def guide_groups():
    conn = get_db()
    guide_id = session['user_id']
    groups_raw = conn.execute("""
        SELECT pg.id, pg.project_title, pg.title_finalized,
               s.name as lead_name, s.prn as lead_roll,
               pg.created_at
        FROM project_group pg
        LEFT JOIN student s ON pg.team_lead_id = s.id
        WHERE pg.guide_id=?
        ORDER BY pg.created_at DESC
    """, (guide_id,)).fetchall()
    groups = []
    for grp in groups_raw:
        members = conn.execute("""
            SELECT s.name, s.prn, s.email,
                   CASE WHEN pg.team_lead_id = s.id THEN 1 ELSE 0 END as is_lead
            FROM group_member gm
            JOIN student s ON gm.student_id = s.id
            JOIN project_group pg ON gm.group_id = pg.id
            WHERE gm.group_id=?
        """, (grp['id'],)).fetchall()
        groups.append({'group': grp, 'members': members})
    conn.close()
    return render_template('guide/groups.html', groups=groups)

@app.route('/guide/titles')
@login_required('guide')
def guide_titles():
    conn = get_db()
    titles = conn.execute("SELECT * FROM project_title WHERE guide_id=? ORDER BY created_at DESC", (session['user_id'],)).fetchall()
    conn.close()
    return render_template('guide/titles.html', titles=titles)

@app.route('/guide/titles/add', methods=['POST'])
@login_required('guide')
def add_title():
    title = request.form.get('title', '').strip()
    if not title:
        flash('Title cannot be empty.', 'error')
        return redirect(url_for('guide_titles'))
    conn = get_db()
    conn.execute("INSERT INTO project_title (guide_id, title) VALUES (?,?)", (session['user_id'], title))
    conn.commit()
    conn.close()
    flash('Project title added.', 'success')
    return redirect(url_for('guide_titles'))

@app.route('/guide/titles/delete/<int:tid>', methods=['POST'])
@login_required('guide')
def delete_title(tid):
    conn = get_db()
    conn.execute("DELETE FROM project_title WHERE id=? AND guide_id=?", (tid, session['user_id']))
    conn.commit()
    conn.close()
    flash('Title removed.', 'success')
    return redirect(url_for('guide_titles'))

@app.route('/guide/submissions')
@login_required('guide')
def guide_submissions():
    conn = get_db()
    groups = conn.execute("""
        SELECT pg.id, pg.project_title, pg.title_finalized, pg.created_at,
               s.name as lead_name, s.prn as lead_roll,
               (SELECT COUNT(*) FROM group_member WHERE group_id=pg.id) as member_count
        FROM project_group pg
        LEFT JOIN student s ON pg.team_lead_id = s.id
        WHERE pg.guide_id=? AND pg.project_title IS NOT NULL AND pg.project_title != ''
        ORDER BY pg.created_at DESC
    """, (session['user_id'],)).fetchall()
    conn.close()
    return render_template('guide/submissions.html', groups=groups)

# ─── GUIDE: PAPER PUBLICATIONS VIEW ─────────────────────────────────────────
@app.route('/guide/papers')
@login_required('guide')
def guide_papers():
    conn = get_db()
    guide_id = session['user_id']
    papers = conn.execute("""
        SELECT pp.*, pg.project_title,
               s.name as lead_name, s.prn as lead_roll
        FROM paper_publication pp
        JOIN project_group pg ON pp.group_id = pg.id
        LEFT JOIN student s ON pg.team_lead_id = s.id
        WHERE pg.guide_id=?
        ORDER BY pp.stage, pp.submitted_at DESC
    """, (guide_id,)).fetchall()
    conn.close()
    return render_template('guide/papers.html', papers=papers)

# ─── ROUTES: STUDENT ────────────────────────────────────────────────────────
@app.route('/student/dashboard')
@login_required('student')
def student_dashboard():
    conn = get_db()
    sid = session['user_id']
    group = conn.execute("""
        SELECT pg.*, g.name as guide_name, g.email as guide_email, g.department as guide_dept,
               s.name as lead_name, s.prn as lead_roll
        FROM group_member gm
        JOIN project_group pg ON gm.group_id = pg.id
        LEFT JOIN guide g ON pg.guide_id = g.id
        LEFT JOIN student s ON pg.team_lead_id = s.id
        WHERE gm.student_id=?
    """, (sid,)).fetchone()

    members = []
    if group:
        members = conn.execute("""
            SELECT s.name, s.prn, s.email,
                   CASE WHEN pg.team_lead_id = s.id THEN 1 ELSE 0 END as is_lead
            FROM group_member gm
            JOIN student s ON gm.student_id = s.id
            JOIN project_group pg ON gm.group_id = pg.id
            WHERE gm.group_id=?
        """, (group['id'],)).fetchall()

    available = []
    if not group:
        available = conn.execute("""
            SELECT s.id, s.name, s.prn, s.division, s.department FROM student s
            WHERE s.id != ?
            AND s.id NOT IN (SELECT student_id FROM group_member)
            ORDER BY s.name
        """, (sid,)).fetchall()

    titles = conn.execute("""
        SELECT pt.id, pt.title, g.name as guide_name
        FROM project_title pt
        JOIN guide g ON pt.guide_id = g.id
        ORDER BY g.name, pt.title
    """).fetchall()

    student = conn.execute("SELECT * FROM student WHERE id=?", (sid,)).fetchone()

    # Fetch paper publications for this group
    papers = {}
    if group:
        pubs = conn.execute(
            "SELECT * FROM paper_publication WHERE group_id=?", (group['id'],)
        ).fetchall()
        for p in pubs:
            papers[p['stage']] = p

    conn.close()
    return render_template('student/dashboard.html',
                           group=group, members=members,
                           available=available, titles=titles,
                           student=student, papers=papers)

@app.route('/student/form-group', methods=['POST'])
@login_required('student')
def form_group():
    sid = session['user_id']
    conn = get_db()

    existing = conn.execute("SELECT group_id FROM group_member WHERE student_id=?", (sid,)).fetchone()
    if existing:
        flash('You are already in a group.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    member_ids = request.form.getlist('members')
    team_lead = request.form.get('team_lead')
    title_type = request.form.get('title_type')
    project_title = request.form.get('project_title', '').strip()
    custom_title = request.form.get('custom_title', '').strip()

    final_title = custom_title if title_type == 'custom' else project_title
    all_members = list(set([str(sid)] + member_ids))

    if len(all_members) < 2:
        flash('Select at least 1 more member.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))
    if len(all_members) > 4:
        flash('Maximum 4 members per group.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))
    if not team_lead:
        flash('Please select a team lead.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    for mid in all_members:
        in_grp = conn.execute("SELECT group_id FROM group_member WHERE student_id=?", (mid,)).fetchone()
        if in_grp:
            s = conn.execute("SELECT name FROM student WHERE id=?", (mid,)).fetchone()
            flash(f'{s["name"]} is already in a group.', 'error')
            conn.close()
            return redirect(url_for('student_dashboard'))

    pg = conn.execute(
        "INSERT INTO project_group (team_lead_id, project_title, title_finalized) VALUES (?,?,0)",
        (team_lead, final_title)
    )
    group_id = pg.lastrowid
    for mid in all_members:
        conn.execute("INSERT INTO group_member (group_id, student_id) VALUES (?,?)", (group_id, mid))
    conn.commit()
    conn.close()
    flash('Group formed successfully! 🎉', 'success')
    return redirect(url_for('student_dashboard'))

@app.route('/student/update-title', methods=['POST'])
@login_required('student')
def update_title():
    sid = session['user_id']
    conn = get_db()

    grp = conn.execute("""
        SELECT pg.id, pg.title_finalized FROM group_member gm
        JOIN project_group pg ON gm.group_id = pg.id
        WHERE gm.student_id=?
    """, (sid,)).fetchone()

    if not grp:
        flash('You are not in a group.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    if grp['title_finalized']:
        flash('Your project title has been finalized by the coordinator and cannot be changed.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    title_type = request.form.get('title_type')
    project_title = request.form.get('project_title', '').strip()
    custom_title = request.form.get('custom_title', '').strip()
    final_title = custom_title if title_type == 'custom' else project_title

    if not final_title:
        flash('Please select or enter a project title.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    conn.execute("UPDATE project_group SET project_title=? WHERE id=?", (final_title, grp['id']))
    conn.commit()
    conn.close()
    flash('✅ Project title updated successfully.', 'success')
    return redirect(url_for('student_dashboard'))

# ─── STUDENT: SUBMIT PAPER PUBLICATION ──────────────────────────────────────
@app.route('/student/submit-paper', methods=['POST'])
@login_required('student')
def submit_paper():
    sid = session['user_id']
    conn = get_db()

    grp = conn.execute("""
        SELECT pg.id FROM group_member gm
        JOIN project_group pg ON gm.group_id = pg.id
        WHERE gm.student_id=?
    """, (sid,)).fetchone()

    if not grp:
        flash('You are not in a group.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    group_id = grp['id']
    stage = request.form.get('stage', type=int)
    paper_title = request.form.get('paper_title', '').strip()
    journal_name = request.form.get('journal_name', '').strip()
    volume_no = request.form.get('volume_no', '').strip()
    issue = request.form.get('issue', '').strip()
    timeline = request.form.get('timeline', '').strip()
    e_issn = request.form.get('e_issn', '').strip()

    if stage not in (1, 2):
        flash('Invalid stage.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    if not all([paper_title, journal_name, volume_no, issue, timeline, e_issn]):
        flash('All publication details are required before uploading the PDF.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    # Handle PDF upload
    pdf_file = request.files.get('pdf_file')
    if not pdf_file or pdf_file.filename == '':
        flash('Please upload the publication PDF.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    if not allowed_file(pdf_file.filename):
        flash('Only PDF files are allowed.', 'error')
        conn.close()
        return redirect(url_for('student_dashboard'))

    # Save PDF with unique name
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    safe_name = secure_filename(pdf_file.filename)
    pdf_filename = f"group{group_id}_stage{stage}_{ts}_{safe_name}"
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], 'papers', pdf_filename)
    pdf_file.save(pdf_path)

    # Delete old PDF if re-submitting
    old = conn.execute(
        "SELECT pdf_filename FROM paper_publication WHERE group_id=? AND stage=?", (group_id, stage)
    ).fetchone()
    if old and old['pdf_filename']:
        old_path = os.path.join(app.config['UPLOAD_FOLDER'], 'papers', old['pdf_filename'])
        if os.path.exists(old_path):
            os.remove(old_path)

    # Upsert
    conn.execute("""
        INSERT INTO paper_publication
            (group_id, stage, paper_title, journal_name, volume_no, issue, timeline, e_issn, pdf_filename, submitted_at)
        VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(group_id, stage) DO UPDATE SET
            paper_title=excluded.paper_title,
            journal_name=excluded.journal_name,
            volume_no=excluded.volume_no,
            issue=excluded.issue,
            timeline=excluded.timeline,
            e_issn=excluded.e_issn,
            pdf_filename=excluded.pdf_filename,
            submitted_at=CURRENT_TIMESTAMP
    """, (group_id, stage, paper_title, journal_name, volume_no, issue, timeline, e_issn, pdf_filename))
    conn.commit()
    conn.close()
    flash(f'✅ Stage {stage} paper publication submitted successfully!', 'success')
    return redirect(url_for('student_dashboard'))

# ─── RUN ────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    print("\n" + "="*55)
    print("  Project Allocation System - Running!")
    print("="*55)
    print("  URL: http://localhost:5500")
    print("  Coordinator: coordinator@college.edu / coord123")
    print("  Students: Email (login) / PRN (password) — after upload")
    print("="*55 + "\n")
    app.run(debug=True, port=5500)
