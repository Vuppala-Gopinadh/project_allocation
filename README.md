# 🏛️ Project Allocation System

A full-featured Flask web application for managing final year project allocations with three portals:
**Coordinator**, **Guide**, and **Student**.

---

## 🚀 Quick Setup

### 1. Install Python (3.9+)
Download from https://python.org

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the App
```bash
python app.py
```

### 4. Open in Browser
Visit: **http://localhost:5000**

---

## 🔑 Default Login Credentials

| Portal | Email | Password |
|--------|-------|----------|
| 📋 Coordinator | coordinator@college.edu | coord123 |
| 🎓 Guide | Set by coordinator | Custom |
| 🎒 Student | Student's email | Roll number (lowercase) |

---

## 📋 Features

### Coordinator Portal
- Upload student list via CSV file
- Add/remove guides with login credentials
- View all formed groups
- Allocate one or multiple guides to groups
- Full allocation overview dashboard

### Guide Portal
- View assigned groups and members
- Add/manage project title suggestions
- View project submissions from groups

### Student Portal
- Form groups of up to 4 members
- Students already in groups are hidden from selection
- Select team lead from group members
- Choose project title from guide's list OR enter custom title
- View assigned guide after coordinator allocates

---

## 📄 CSV Upload Format

```
name,rollno,department,email
John Doe,CS001,Computer Science,john@student.edu
Jane Smith,CS002,Computer Science,jane@student.edu
```

A sample file is provided at `static/sample_students.csv`

---

## 📁 Project Structure

```
project_allocation/
├── app.py                     # Main Flask application
├── requirements.txt           # Python dependencies
├── static/
│   └── sample_students.csv    # Sample student CSV
├── templates/
│   ├── base.html              # Base layout template
│   ├── login.html             # Login page
│   ├── coordinator/
│   │   ├── dashboard.html
│   │   ├── students.html
│   │   ├── guides.html
│   │   ├── groups.html
│   │   └── allocations.html
│   ├── guide/
│   │   ├── dashboard.html
│   │   ├── groups.html
│   │   ├── titles.html
│   │   └── submissions.html
│   └── student/
│       └── dashboard.html
└── instance/
    └── project_allocation.db  # SQLite database (auto-created)
```

---

## 🔧 Configuration

Edit `app.py` to change:
- `app.secret_key` — Session security key
- Default coordinator credentials (in `init_db()`)
- Port number (default: 5000)

---

## 🛠️ Tech Stack

- **Backend**: Python Flask
- **Database**: SQLite (via sqlite3)
- **Auth**: Werkzeug password hashing
- **Frontend**: Pure HTML/CSS/JS (no framework needed)
- **Fonts**: DM Sans + DM Mono (Google Fonts)
