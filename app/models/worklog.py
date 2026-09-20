"""WorkLog model: actual time logged against a specific project.

Every row is project-scoped: the same user can log time in many projects and
the per-project totals are always computed by filtering on ``project_id``.

Audit model — two distinct concepts are stored:

* ``worked_by_user_id`` — the person who actually performed the work.
* ``logged_by_user_id`` — the authenticated user who entered the record
  (set by the backend from the session, never trusted from the frontend).

Team Work Time is aggregated ONLY from these explicit work logs. Nothing else
(login sessions, page activity, assignment, story points, status changes) is
ever treated as work time.
"""
from datetime import datetime

from app.extensions import db


class WorkLog(db.Model):
    __tablename__ = 'work_logs'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    issue_id = db.Column(db.Integer, db.ForeignKey('issues.id'), nullable=True)
    worked_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    logged_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    work_date = db.Column(db.Date, nullable=False)
    # Wall-clock start/end times on ``work_date``, canonical 24-hour 'HH:MM'.
    # Overnight work is not supported: the backend requires end >= start on the
    # same date (end == start is rejected as zero duration). These columns stay
    # nullable only so legacy records (created before start/end existed) keep
    # their original ``duration_minutes`` unchanged.
    start_time = db.Column(db.String(5), nullable=True)
    end_time = db.Column(db.String(5), nullable=True)
    # duration_minutes is ALWAYS recomputed on the backend from start/end. The
    # frontend never supplies it (any submitted value is ignored).
    duration_minutes = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', foreign_keys=[project_id])
    worked_by = db.relationship('User', foreign_keys=[worked_by_user_id])
    logged_by = db.relationship('User', foreign_keys=[logged_by_user_id])
    issue = db.relationship('Issue', foreign_keys=[issue_id])

    __table_args__ = (
        db.Index('ix_work_logs_project_user', 'project_id', 'worked_by_user_id'),
        db.Index('ix_work_logs_project_date', 'project_id', 'work_date'),
        db.Index('ix_work_logs_issue', 'issue_id'),
        db.Index('ix_work_logs_logged_by', 'logged_by_user_id'),
    )