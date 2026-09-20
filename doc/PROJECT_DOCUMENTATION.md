# Project Documentation — Wexira

> A Flask + SQLAlchemy team workspace / issue tracker with a versioned REST API,
> a server-rendered Jira-style UI, and Swagger documentation.

---

## 1. Overview

**Wexira** is a self-contained workspace application built on Flask. It offers:

- Multi-project, multi-sprint issue tracking (Story / Bug / Task / Epic)
- Lazy-loaded, expandable **subtask (task tree)** rows
- Story points, priorities, custom statuses, badges
- Team work-time logging and working-hours tracking
- Comments, notifications, activity + audit log
- Dashboard, reports, team views
- Versioned JSON API (`/api/v1`) with Swagger UI

---

## 2. Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.10+ |
| Web framework | Flask 3.1 (Flask-SQLAlchemy, Flask-Login) |
| Database | PostgreSQL (psycopg2) — `DATABASE_URL` env; SQLite compatible for dev |
| Templating | Jinja2 (server-rendered + inline JS interactive tree) |
| API docs | Swagger UI at `/swagger` built from `swagger_spec.py` |
| Assets | Tailwind-style utility classes, Lucide icons |

---

## 3. Project Layout

```
sample_flaskapi_api/
├── run.py                    # Entry point: create_app() + app.run()
├── seed.py                   # Seed demo data
├── requirements.txt
├── .env                      # Local env (DATABASE_URL, SECRET_KEY)
├── DATABASE_DESIGN.md        # Data model / ERD reference
├── doc/                      # Project docs
│   ├── PROJECT_DOCUMENTATION.md
│   └── WORKFLOW.md
├── app/
│   ├── __init__.py           # create_app() factory, blueprints, request hooks
│   ├── config.py             # Config (reads env / .env)
│   ├── extensions.py         # SQLAlchemy & Flask-Login instances
│   ├── models/               # SQLAlchemy models (re-exported)
│   ├── services/             # Business logic layer
│   ├── api/v1/               # Versioned REST blueprints
│   ├── routes/               # Server-rendered page routes
│   └── utils/                # Helpers, decorators, bootstrap
├── templates/                # Jinja2 templates
│   └── projects/project_overview.html   # Task/subtask tree table
└── static/js/api.js          # Shared API client
```

---

## 4. Getting Started

### 4.1 Environment

```bash
python -m venv env
env\Scripts\activate           # Windows
pip install -r requirements.txt
```

### 4.2 Configuration

Config lives in `app/config.py` and reads from env / `.env`:

| Env var | Default | Purpose |
|---------|---------|---------|
| `DATABASE_URL` | `postgresql://wexira:wexira@127.0.0.1:5432/wexira` | SQLAlchemy string |
| `SECRET_KEY` | `wexira-secret` | Flask session key |
| `FLASK_DEBUG` | `1` | Debug mode |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Bind address |

> Local/zero-dep run: set `DATABASE_URL` to a SQLite path, e.g.
> `sqlite:////absolute/path/project.db`.

### 4.3 Run

```bash
python run.py
```

- App UI: <http://127.0.0.1:5000/>
- Swagger UI: <http://127.0.0.1:5000/swagger>
- OpenAPI JSON: <http://127.0.0.1:5000/swagger.json>

### 4.4 Seed

```bash
python seed.py
```

---

## 5. Architecture

### 5.1 Application Factory

`create_app()` in `app/__init__.py`:

1. Builds the Flask instance pointing at `templates/` + `static/`.
2. Loads `Config`.
3. Initializes `db` and `login_manager`.
4. Registers request hooks (last-seen heartbeat, auth gating).
5. Registers versioned API blueprints under `/api/v1`.
6. Registers page routes.
7. Bootstraps the database.

### 5.2 Blueprints (API v1)

| Blueprint | Prefix | Responsibility |
|-----------|--------|----------------|
| `auth_bp` | `/auth` | Login / register / logout |
| `users_bp` | `/users` | User profiles, notifications prefs |
| `projects_bp` | `/projects` | Project CRUD, members |
| `sprints_bp` | `/sprints` | Sprint planning & lifecycle |
| `issues_bp` | `/issues` | Issue CRUD, subtasks, assignees |
| `comments_bp` | `/comments` | Issue comments |
| `notifications_bp` | `/notifications` | Notifications |
| `dashboard_bp` | `/dashboard` | Aggregated views |
| `reports_bp` | `/reports` | Issue reports |
| `team_bp` | `/team` | Team work time |
| `ai_bp` | `/ai` | AI helpers |
| `worklogs_bp` | `/worklogs` | Work time logging |

### 5.3 Layering

- **Models** (`app/models/`) — pure SQLAlchemy classes, no Flask imports.
- **Services** (`app/services/`) — business logic used by API + page routes.
- **API v1** — blueprint handlers calling services, JSON out.
- **Routes/Pages** — Jinja-rendered UI.
- **Utils** — cross-cutting helpers (`decorators`, `validators`, `bootstrap`).

---

## 6. Data Model

See [`DATABASE_DESIGN.md`](../DATABASE_DESIGN.md) for full schema. Core entities:

- **Users** — accounts, initials, role, team, capacity
- **Projects** — containers for sprints & issues, health indicators
- **ProjectMembers** — many-to-many user ↔ project
- **Sprints** — iterations with per-status counts & story points
- **Issues** — work items; status, priority, assignee, sprint, points, due date,
  working minutes, subtask links
- **IssueAssignees** — many-to-many issue ↔ user
- **Comments / Activities / Notifications** — collaboration & audit
- **WorkLogs / WorkTimers** — time tracking feeding "Working Hours"
- **WorkspaceSettings** — workspace defaults

### Issue Tasks table (UI) — 9 columns

The project overview renders the task table as **9 columns**. Any UI row/Patch
that columns must keep this exact order:

`Task | Priority | Sprint | Assignee | Start Date | Due Date | Status | Working Hours | Commands`

Empty-state rows use `colspan="9"`. The JS `updateTaskRow` maps `tds[3] = Assignee`
and the "Working Hours" cell lives at `td:nth-child(8)`.

---

## 7. API Conventions

- Base path: `/api/v1`
- Responses: JSON. Errors: `{ "ok": false, "error": "..." }`.
- Auth via `Flask-Login` session; API routes return `401` JSON when unauthenticated.
- Swagger spec is centralized in `swagger_spec.py`.

---

## 8. Tasks / Broader Notes

- Use `git status` / `git diff` before committing; never commit secrets.
- Run the app and open `/swagger` to exercise endpoints.
- Subtask tree is lazy-loaded on expand; subtask rows are rendered client-side
  (`ptSubrowHtml`) and follow the same 9-column layout.
</content>
