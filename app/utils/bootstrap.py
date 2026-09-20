"""Startup bootstrap: create tables, run lightweight schema upgrades, seed
workspace defaults.

This mirrors the ``if __name__ == '__main__':`` block from the original
monolith so ``python run.py`` behaves exactly like the old ``python app.py``.
"""
from sqlalchemy import inspect as sa_inspect, text as sa_text

from app.extensions import db
from app.utils.helpers import seed_settings_defaults


def run_schema_upgrades(app):
    """Idempotent ALTER-based schema upgrades for legacy databases.

    Runs inside an app context; any failure is intentionally swallowed so the
    app still boots (columns exist when created through the models).
    """
    try:
        inspector = sa_inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('users')]
        if 'last_seen' not in columns:
            db.session.execute(sa_text('ALTER TABLE users ADD COLUMN last_seen TIMESTAMP'))
            db.session.commit()
        if 'created_at' not in columns:
            db.session.execute(sa_text('ALTER TABLE users ADD COLUMN created_at TIMESTAMP'))
            db.session.commit()
        if 'updated_at' not in columns:
            db.session.execute(sa_text('ALTER TABLE users ADD COLUMN updated_at TIMESTAMP'))
            db.session.commit()
        if 'permission_role' not in columns:
            db.session.execute(sa_text(
                "ALTER TABLE users ADD COLUMN permission_role VARCHAR(40) NOT NULL DEFAULT 'member'"))
            db.session.commit()
        issue_cols = [col['name'] for col in inspector.get_columns('issues')]
        if 'start_date' not in issue_cols:
            db.session.execute(sa_text("ALTER TABLE issues ADD COLUMN start_date VARCHAR(40)"))
            db.session.commit()
        if 'working_minutes' not in issue_cols:
            db.session.execute(sa_text("ALTER TABLE issues ADD COLUMN working_minutes INTEGER"))
            db.session.commit()
        if 'completed_at' not in issue_cols:
            db.session.execute(sa_text("ALTER TABLE issues ADD COLUMN completed_at TIMESTAMP"))
            db.session.commit()
        if 'parent_issue_id' not in issue_cols:
            db.session.execute(sa_text(
                "ALTER TABLE issues ADD COLUMN parent_issue_id INTEGER REFERENCES issues(id)"))
            db.session.commit()
        if 'subtask_order' not in issue_cols:
            db.session.execute(sa_text(
                "ALTER TABLE issues ADD COLUMN subtask_order INTEGER DEFAULT 0 NOT NULL"))
            db.session.commit()
        # Backfill/renumber subtask order (1..N per parent, by position then id).
        db.session.execute(sa_text(
            "UPDATE issues SET subtask_order = rn FROM ("
            "  SELECT id, row_number() OVER ("
            "    PARTITION BY parent_issue_id ORDER BY COALESCE(position, 0), id"
            "  ) AS rn FROM issues WHERE parent_issue_id IS NOT NULL"
            ") r WHERE issues.id = r.id"))
        db.session.commit()
        sprint_cols = [col['name'] for col in inspector.get_columns('sprints')]
        if 'description' not in sprint_cols:
            db.session.execute(sa_text("ALTER TABLE sprints ADD COLUMN description TEXT"))
            db.session.commit()
        notif_cols = [col['name'] for col in inspector.get_columns('notifications')]
        notif_new = {
            'recipient_id': 'INTEGER',
            'actor_id': 'INTEGER',
            'project_id': 'INTEGER',
            'issue_id': 'INTEGER',
            'sprint_id': 'INTEGER',
            'type': "VARCHAR(40) DEFAULT 'system'",
            'category': "VARCHAR(20) DEFAULT 'updates'",
            'priority': "VARCHAR(20) DEFAULT 'normal'",
            'message': "TEXT DEFAULT ''",
            'event_key': 'VARCHAR(200)',
            'metadata': 'JSONB',
            'read_at': 'TIMESTAMP',
            'deleted_at': 'TIMESTAMP',
            'created_dt': 'TIMESTAMP',
        }
        for col_name, col_def in notif_new.items():
            if col_name not in notif_cols:
                db.session.execute(sa_text(f'ALTER TABLE notifications ADD COLUMN {col_name} {col_def}'))
                db.session.commit()
        db.session.execute(sa_text('CREATE INDEX IF NOT EXISTS ix_notif_recipient_read ON notifications(recipient_id, is_read)'))
        db.session.execute(sa_text('CREATE INDEX IF NOT EXISTS ix_notif_recipient_created ON notifications(recipient_id, created_dt)'))
        db.session.commit()
        db.session.execute(sa_text('CREATE INDEX IF NOT EXISTS ix_notif_recipient_category ON notifications(recipient_id, category)'))
        db.session.commit()
        db.session.execute(sa_text("CREATE UNIQUE INDEX IF NOT EXISTS uq_notif_event_key ON notifications(event_key) WHERE event_key IS NOT NULL"))
        db.session.commit()
        db.session.execute(sa_text("""
            UPDATE notifications
            SET recipient_id = 1,
                category = COALESCE(notification_type, 'updates'),
                created_dt = COALESCE(t.dt, created_dt)
            FROM (
                SELECT id, NOW() - INTERVAL '1 hour' * row_number() OVER (ORDER BY id) AS dt
                FROM notifications WHERE recipient_id IS NULL
            ) t
            WHERE notifications.id = t.id
        """))
        db.session.commit()
        # WorkLog audit schema (Team Work Time): the legacy column `user_id`
        # (the person who performed the work) is safely renamed to
        # `worked_by_user_id` and a new `logged_by_user_id` column records who
        # entered the log. Handled as a proper, idempotent, non-destructive
        # migration: backfill happens before the old column is dropped and
        # existing rows are never deleted.
        try:
            wl_cols = [col['name'] for col in inspector.get_columns('work_logs')]
        except Exception:
            wl_cols = []
        if wl_cols:
            if 'user_id' in wl_cols:
                if 'worked_by_user_id' not in wl_cols:
                    db.session.execute(sa_text('ALTER TABLE work_logs ADD COLUMN worked_by_user_id INTEGER'))
                    db.session.commit()
                if 'logged_by_user_id' not in wl_cols:
                    db.session.execute(sa_text('ALTER TABLE work_logs ADD COLUMN logged_by_user_id INTEGER'))
                    db.session.commit()
                db.session.execute(sa_text(
                    'UPDATE work_logs SET worked_by_user_id = user_id '
                    'WHERE worked_by_user_id IS NULL'))
                db.session.commit()
                db.session.execute(sa_text(
                    'UPDATE work_logs SET logged_by_user_id = '
                    'COALESCE(logged_by_user_id, worked_by_user_id) '
                    'WHERE logged_by_user_id IS NULL'))
                db.session.commit()
                db.session.execute(sa_text('ALTER TABLE work_logs DROP COLUMN user_id'))
                db.session.commit()
            else:
                if 'worked_by_user_id' not in wl_cols:
                    db.session.execute(sa_text('ALTER TABLE work_logs ADD COLUMN worked_by_user_id INTEGER'))
                    db.session.commit()
                if 'logged_by_user_id' not in wl_cols:
                    db.session.execute(sa_text('ALTER TABLE work_logs ADD COLUMN logged_by_user_id INTEGER'))
                    db.session.commit()
                db.session.execute(sa_text(
                    'UPDATE work_logs SET logged_by_user_id = worked_by_user_id '
                    'WHERE logged_by_user_id IS NULL'))
                db.session.commit()
            db.session.execute(sa_text(
                'CREATE INDEX IF NOT EXISTS ix_work_logs_project_user '
                'ON work_logs(project_id, worked_by_user_id)'))
            db.session.execute(sa_text(
                'CREATE INDEX IF NOT EXISTS ix_work_logs_logged_by '
                'ON work_logs(logged_by_user_id)'))
            db.session.commit()
            # Start/end wall-clock times (canonical 24-hour 'HH:MM'). Added
            # idempotently; existing rows keep their original duration. The
            # backend recomputes duration from start/end on every write, so a
            # client-supplied duration is never trusted either way.
            if 'start_time' not in wl_cols:
                db.session.execute(sa_text('ALTER TABLE work_logs ADD COLUMN start_time VARCHAR(5)'))
                db.session.commit()
            if 'end_time' not in wl_cols:
                db.session.execute(sa_text('ALTER TABLE work_logs ADD COLUMN end_time VARCHAR(5)'))
                db.session.commit()
    except Exception:
        pass
    # Work timer (automatic Start/Stop Work sessions). The table is created by
    # db.create_all() through the model; this backup stays safe on every boot
    # for databases where the table or its partial unique index already exist.
    try:
        timer_cols = []
        try:
            timer_cols = [col['name'] for col in sa_inspect(db.engine).get_columns('work_timers')]
        except Exception:
            timer_cols = []
        if timer_cols:
            db.session.execute(sa_text("CREATE UNIQUE INDEX IF NOT EXISTS uq_work_timer_one_active ON work_timers(user_id) WHERE stopped_at IS NULL"))
            db.session.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_work_timer_user ON work_timers(user_id)"))
            db.session.execute(sa_text("CREATE INDEX IF NOT EXISTS ix_work_timer_issue ON work_timers(issue_id)"))
            db.session.commit()
    except Exception:
        pass


def bootstrap_database(app):
    """Create missing tables, apply schema upgrades and seed defaults."""
    with app.app_context():
        db.create_all()
        run_schema_upgrades(app)
        seed_settings_defaults()