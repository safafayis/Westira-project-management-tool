# Workflow — Wexira

How changes move through this Flask project, plus the day-to-day task model.

---

## 1. Running Everyday

Spin up the server:

```bash
env\Scripts\activate
python run.py
```

Open <http://127.0.0.1:5000/> and sign in (seeded users are created by
`seed.py`). API docs live at `/swagger`.

---

## 2. Where Code Lives (mapping)

| Concern | Location |
|---------|----------|
| Flask app factory / config | `app/__init__.py`, `app/config.py` |
| Database classes | `app/models/` |
| Business logic | `app/services/` |
| JSON API endpoints | `app/api/v1/` (blueprints) |
| Server-rendered pages | `app/routes/` |
| Shared helpers / decorators | `app/utils/` |
| HTML / JS views | `templates/` + `static/js/` |
| OpenAPI / Swagger | `swagger_spec.py` |

---

## 3. Typical Change Flow

1. **Model change** → edit the SQLAlchemy class in `app/models/`, then either
   recreate the DB (dev) or add a migration.
2. **Business rule** → add/update in `app/services/` so both API and pages reuse
   it.
3. **Endpoint** → new method in an `app/api/v1/*.py` blueprint, return JSON,
   document in `swagger_spec.py`.
4. **Page** → Jinja template in `templates/`; keep any embedded JS in sync with
   the rendered table columns.
5. **Verify** → `python verify_full_run.py` runs the API smoke suite against the
   running app.

---

## 4. Hourly / Daily Task Loop

1. Open the **Project Tasks** table (`/projects/<key>`).
2. Top-level tasks are server-rendered; click the chevron to lazy-load subtasks.
3. Edit / delete subtasks via the command buttons in each row; edits refresh the
   parent's counts and Working Hours in place.
4. Log work → working minutes roll up into the parent and the sprint totals.

---

## 5. Table Column Contract

The task table is **9 columns**: Task, Priority, Sprint, Assignee, Start Date,
Due Date, Status, Working Hours, Commands.

Keep in sync everywhere:

- Server header `<th>` and empty-state rows (`colspan="9"`).
- Server task rows (`<td>` order must match the header).
- JS `updateTaskRow` (uses `tds[3]` = Assignee; Working Hours cell selector is
  `td:nth-child(8)`).
- JS subtask row builder `ptSubrowHtml` (same 9 `<td>`s).

If you add/remove a column, update **all** of the above — a lone mismatch shifts
every cell after it.

---

## 6. Verify & Lint

No separate test runner; use the bundled verification:

```bash
python verify_full_run.py
```

It starts a client session, hits the `/api/v1` endpoints end-to-end, and prints
a pass/fail summary. After UI/JS edits, also reload the page and exercise the
subtask expand → edit → delete path manually.

---

## 7. Housekeeping

- Never commit `.env`, `*.db`, or the `env/` virtualenv (see `.gitignore`).
- Do not commit secrets.
- Keep `DATABASE_DESIGN.md` and this `doc/` folder in sync with schema/UI
  changes.
</content>
